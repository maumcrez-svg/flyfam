"""One collector. One normalisation path. Replay and live share it.

docs/SPEC.md D10 addenda 6 and 7. The shape of a tick is deliberately small:

1. ``eth_getBlockByNumber("latest")`` — one request, and the head we will
   reason about for this tick.
2. one ``eth_getLogs`` over ``[cursor+1, head]`` for the factory;
3. one ``eth_getLogs`` over the same range for the **tracked curve addresses**.

Three requests a tick at the 30-second cadence, whatever the number of curves,
because the address list goes into the filter instead of into a loop. A
`logs` WebSocket subscription would be billed per delivered push
(docs.chainstack.com/docs/request-units) — thousands an hour at this launch
rate — which is why this wave polls and *reports* the comparison as a number.

**The header is the real cost, measured rather than assumed.** A log carries
no timestamp, so normalising one needs its block header: a tick costs those
three requests **plus one ``eth_getBlockByNumber`` per distinct block that
carried an event**, cached by hash so a block is paid for once ever. With the
interval measured at ~0.1 s (``experiments/d10/finality.json``) a 30-second
tick spans ~300 blocks and, at the measured launch rate, most of them carry
something — so a live run spends its budget on headers, not on logs, and the
live cap has to be read that way.

Reorg handling is the other half. A log arriving with ``removed: true``, or a
block whose stored hash no longer matches the chain, orphans the events in the
affected blocks, rewinds the cursor to the last confirmed block and re-reads.
Raw evidence is kept; orphaned events never feed context again. And
**confirmation**: decisions may use the fast stream, but an outcome may only
settle on blocks that are confirmed, so a rollback cannot have taught anything.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from . import abi
from .budget import BudgetStop
from .curve import CurveState
from .manifest import Manifest
from .rpc import RANGE_TOO_LARGE, RpcClient, RpcError, keccak256_hex
from .storage import ChainStore, log_id, order_key

NORMALISER_VERSION = "pons-normalise-1"

#: Addendum 6: the donor's chunk size, used only when a range is larger than
#: one tick's worth of blocks, and the floor a halving range retreat stops at.
CHUNK_BLOCKS = 25
MIN_CHUNK_BLOCKS = 25

#: Reviewer decision 1: the bounded-backfill chunk sizes. The factory filter
#: is one address and matches a handful of logs per thousand blocks; the
#: tracked-curve filter is hundreds of addresses and is asked for less.
FACTORY_CHUNK_BLOCKS = 1_000
CURVE_CHUNK_BLOCKS = 500

#: How many addresses may go into one ``eth_getLogs`` filter. Not a provider
#: limit we were told: a self-imposed bound so one refused request costs one
#: retreat rather than the whole tracked set.
MAX_FILTER_ADDRESSES = 250

#: Reviewer decision 2: headers are fetched on a sparse grid, one per this
#: many blocks, plus the ``latest`` header of each tick. At the measured
#: interval of ~0.101 s that is a header every ~10 s of chain time, and it is
#: what makes a 30-second tick (≈300 blocks) cost three headers instead of
#: three hundred. Timestamps between grid points are linearly interpolated and
#: carry ``interpolated: true`` with the declared precision below.
HEADER_GRID_BLOCKS = 100

#: Addendum 6: at most the last hour of blocks is backfilled at start, so a
#: tracked curve has its history without a genesis scan.
BACKFILL_SECONDS = 3_600

#: Addendum 7: a block is confirmed once it is this many seconds behind head.
CONFIRM_SECONDS = 60

#: Addendum 6: a curve is tracked while it is this young, or while we hold it.
TRACK_SECONDS = 3_600


class CollectorStop(RuntimeError):
    """A clean stop: the cursor, ledger and events are on disk."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _int(value) -> int:
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def _jsonable(args: dict) -> dict:
    """Integers become decimal strings: a uint256 does not fit a JSON number."""
    out = {}
    for key, value in args.items():
        out[key] = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    return out


# --------------------------------------------------------------------------
# Block time on a sparse grid (reviewer decision 2)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BlockTime:
    """When a block happened, and how well we know it.

    ``interpolated`` is the whole point. A timestamp read from that block's own
    header is exact and says so; a timestamp interpolated between two grid
    anchors says so too, and carries ``precision_s`` — the grid interval in
    seconds — rather than pretending to the exactness of a header we did not
    buy. Every derived timestamp that reaches an artifact carries both fields.
    """

    number: int
    timestamp: int
    interpolated: bool
    precision_s: float
    anchor_below: int | None = None
    anchor_above: int | None = None
    block_hash: str = ""

    def as_dict(self) -> dict:
        return {"block_number": self.number, "block_timestamp": self.timestamp,
                "interpolated": self.interpolated,
                "precision_s": self.precision_s,
                "anchor_below": self.anchor_below,
                "anchor_above": self.anchor_above}


class HeaderGrid:
    """Sparse block headers, plus linear interpolation between them.

    A log carries no timestamp, so normalising one needs to know when its block
    happened. Buying a header per block costs one request per block that
    carried an event, which on this chain — ~0.1 s blocks, ~520 launches an
    hour — is the dominant cost of a run and was measured as such in dispatch
    1. So headers are bought on a grid of one per
    :data:`HEADER_GRID_BLOCKS` blocks and everything between two anchors is
    interpolated::

        t(n) = t(below) + (t(above) - t(below)) * (n - below) / (above - below)

    **Hash anchoring still holds**, in two places rather than one: at a grid
    point the header is real and its hash is stored and re-read, and every log
    carries its own ``blockHash``, which is what the log id, the dedup set and
    the reorg rule are keyed on. What is lost is the per-block header hash of
    blocks between grid points, and what replaces it is the log's own — which
    is the same field the chain signs the log into.
    """

    def __init__(self, rpc: RpcClient, store: ChainStore, *,
                 grid_blocks: int = HEADER_GRID_BLOCKS, interval_s: float,
                 ceiling: int | None = None):
        self.rpc = rpc
        self.store = store
        self.grid_blocks = max(1, int(grid_blocks))
        self.interval_s = float(interval_s)
        self.precision_s = round(self.grid_blocks * self.interval_s, 6)
        self.ceiling = None if ceiling is None else int(ceiling)
        self.fetched = 0

    # ------------------------------------------------------------- anchors
    def header_at(self, number: int) -> dict:
        """That exact block's header, from the store or from one request."""
        number = max(0, int(number))
        known = self.store.headers_by_number.get(number)
        if known is not None:
            return known
        header = self.rpc.block(number)
        self.store.record_headers([header])
        self.fetched += 1
        return self.store.headers_by_number[number]

    def anchor_number(self, number: int) -> int:
        return (max(0, int(number)) // self.grid_blocks) * self.grid_blocks

    def anchor_below(self, number: int) -> dict:
        """The grid header at or below ``number``. One request at most."""
        return self.header_at(self.anchor_number(number))

    def warm(self, first: int, last: int) -> int:
        """Fetch every grid anchor covering ``[first, last]``. Returns how many."""
        before = self.fetched
        lo = self.anchor_number(first)
        top = self.anchor_number(last) + self.grid_blocks
        if self.ceiling is not None:
            top = min(top, self.ceiling)
        n = lo
        while n <= top:
            self.header_at(n)
            n += self.grid_blocks
        if self.ceiling is not None and top < self.anchor_number(last) + self.grid_blocks:
            self.header_at(self.ceiling)
        return self.fetched - before

    # ---------------------------------------------------------------- time
    def time(self, number: int) -> BlockTime:
        """When block ``number`` happened, exactly or interpolated."""
        n = max(0, int(number))
        known = self.store.headers_by_number.get(n)
        if known is not None:
            return BlockTime(n, int(known["timestamp"]), False, 0.0,
                             anchor_below=n, anchor_above=n,
                             block_hash=str(known["hash"]))
        below = self.anchor_below(n)
        if int(below["number"]) == n:            # n is itself a grid point
            return BlockTime(n, int(below["timestamp"]), False, 0.0,
                             anchor_below=n, anchor_above=n,
                             block_hash=str(below["hash"]))
        upper = self.anchor_number(n) + self.grid_blocks
        if self.ceiling is not None and upper > self.ceiling:
            upper = self.ceiling
        above = self.header_at(upper) if upper > int(below["number"]) else below
        span = int(above["number"]) - int(below["number"])
        if span <= 0:
            timestamp = int(below["timestamp"])
        else:
            delta = int(above["timestamp"]) - int(below["timestamp"])
            timestamp = int(below["timestamp"]) + int(
                round(delta * (n - int(below["number"])) / span))
        return BlockTime(n, timestamp, True, self.precision_s,
                         anchor_below=int(below["number"]),
                         anchor_above=int(above["number"]))


class BlockClock:
    """Timestamp → block number: the inverse of :class:`HeaderGrid`.

    The fill rule needs "the first block whose timestamp is at or after
    ``t + latency``", and a token that has stopped trading has no event there
    to read a block number off. So the same sparse anchors that give a block
    its timestamp are inverted to give a timestamp its block, by the same
    linear rule, and the answer says whether it was interpolated and to what
    precision. It never invents a block outside the anchors it holds.
    """

    def __init__(self, headers, *, interval_s: float,
                 grid_blocks: int = HEADER_GRID_BLOCKS):
        pairs = sorted({int(h["number"]): int(h["timestamp"]) for h in headers}.items())
        if not pairs:
            raise ValueError("a block clock needs at least one header")
        self.numbers = [n for n, _ in pairs]
        self.times = [t for _, t in pairs]
        self.interval_s = float(interval_s)
        self.precision_s = round(grid_blocks * self.interval_s, 6)
        self.first_block, self.first_ts = pairs[0]
        self.last_block, self.last_ts = pairs[-1]

    def _bracket(self, timestamp: int):
        import bisect
        i = bisect.bisect_left(self.times, int(timestamp))
        if i <= 0:
            return 0, 0
        if i >= len(self.times):
            return len(self.times) - 1, len(self.times) - 1
        return i - 1, i

    def block_at_or_after(self, timestamp: int) -> dict:
        """``{block_number, block_timestamp, interpolated, precision_s}``.

        ``None`` when the timestamp is past the last anchor: that is missing
        coverage, and the caller must say so rather than clamp to the end.
        """
        timestamp = int(timestamp)
        if timestamp <= self.first_ts:
            return {"block_number": self.first_block,
                    "block_timestamp": self.first_ts,
                    "interpolated": False, "precision_s": 0.0}
        if timestamp > self.last_ts:
            return {}
        lo, hi = self._bracket(timestamp)
        t0, t1 = self.times[lo], self.times[hi]
        n0, n1 = self.numbers[lo], self.numbers[hi]
        if t1 == timestamp or t0 == t1:
            return {"block_number": n1, "block_timestamp": t1,
                    "interpolated": False, "precision_s": 0.0}
        span_t, span_n = t1 - t0, n1 - n0
        # the first block whose interpolated timestamp reaches ``timestamp``
        offset = -(-(timestamp - t0) * span_n // span_t)
        number = min(n1, n0 + int(offset))
        stamped = t0 + int(round((number - n0) * span_t / span_n))
        return {"block_number": int(number), "block_timestamp": int(stamped),
                "interpolated": True, "precision_s": self.precision_s}


# --------------------------------------------------------------------------
# Normalisation — the one path (addendum 8: replay and live are one code path)
# --------------------------------------------------------------------------
class Normaliser:
    """``normalise(raw_log, header) -> event``, bound to a manifest and markets.

    ``markets`` maps a curve address to its launch record; a log from an
    address that is neither the supported factory nor a known curve is
    normalised as ``UNKNOWN_SOURCE`` and decoded by nobody. That refusal is
    the reason a v1 launch or a V4 pool event can never arrive here wearing
    the curve ABI.
    """

    version = NORMALISER_VERSION

    def __init__(self, manifest: Manifest, markets: dict | None = None):
        self.manifest = manifest
        self.factory = manifest.factory.address
        self.markets: dict[str, dict] = dict(markets or {})

    def register_market(self, curve: str, record: dict) -> None:
        self.markets[str(curve).lower()] = record

    def __call__(self, raw_log: dict, header) -> dict:
        return self.normalise(raw_log, header)

    def normalise(self, raw_log: dict, header) -> dict:
        """``header`` is a real block header **or** a :class:`BlockTime`.

        A real header is checked hash-for-hash against the log, as it always
        was, and its timestamp is exact. A :class:`BlockTime` comes off the
        sparse grid (reviewer decision 2): when it is interpolated the event
        carries ``block_timestamp_interpolated`` and
        ``block_timestamp_precision_s`` so no reader can mistake a derived
        timestamp for a read one. Those two keys are written **only** when the
        timestamp really was interpolated, so an event normalised from a real
        header is byte-identical to one normalised before the grid existed.
        """
        address = str(raw_log["address"]).lower()
        block_number = _int(raw_log["blockNumber"])
        block_hash = str(raw_log["blockHash"]).lower()
        interpolated = False
        precision_s = 0.0
        if isinstance(header, BlockTime):
            if header.block_hash and str(header.block_hash).lower() != block_hash:
                raise RpcError("HEADER_HASH_MISMATCH",
                               f"{header.block_hash} != {block_hash}")
            if int(header.number) != block_number:
                raise RpcError("HEADER_NUMBER_MISMATCH",
                               f"{header.number} != {block_number}")
            timestamp = int(header.timestamp)
            interpolated = bool(header.interpolated)
            precision_s = float(header.precision_s)
        else:
            header_hash = str(header["hash"]).lower()
            if header_hash != block_hash:
                raise RpcError("HEADER_HASH_MISMATCH",
                               f"{header_hash} != {block_hash}")
            timestamp = _int(header["timestamp"])
        event = {
            "log_id": log_id(raw_log),
            "chain_id": self.manifest.chain_id,
            "venue": "PONS",
            "normaliser": self.version,
            "address": address,
            "block_number": block_number,
            "block_hash": block_hash,
            "block_timestamp": timestamp,
            "tx_hash": str(raw_log["transactionHash"]).lower(),
            "tx_index": _int(raw_log["transactionIndex"]),
            "log_index": _int(raw_log["logIndex"]),
            "removed": bool(raw_log.get("removed", False)),
            "token": None,
            "curve": None,
            "deployment": None,
            "source": None,
            "status": "OK",
            "reason": None,
            "event": "unmapped",
            "args": {},
            "error": None,
        }
        if interpolated:
            event["block_timestamp_interpolated"] = True
            event["block_timestamp_precision_s"] = precision_s
        if address == self.factory:
            event["source"] = "factory"
            event["deployment"] = self.manifest.factory.id
            decoded = abi.decode_factory_log(raw_log)
        elif address in self.markets:
            market = self.markets[address]
            event["source"] = "curve"
            event["curve"] = address
            event["token"] = market.get("token")
            event["deployment"] = market.get("deployment")
            decoded = abi.decode_curve_log(raw_log)
        else:
            other = self.manifest.by_address(address)
            event["source"] = "unknown"
            event["status"] = "UNSUPPORTED" if other else "UNKNOWN_SOURCE"
            event["reason"] = (other.reason if other else
                               "address is neither the supported factory nor a tracked curve")
            if other:
                event["deployment"] = other.id
            return event
        event["event"] = decoded["event"]
        event["args"] = _jsonable(decoded.get("args") or {})
        event["error"] = decoded.get("error")
        if decoded["event"] == "unsupported":
            event["status"] = "UNSUPPORTED"
            event["reason"] = decoded.get("reason")
        elif decoded["event"] == "unmapped":
            event["status"] = "UNMAPPED"
            event["reason"] = "topic0 not in the pinned ABI"
        elif decoded.get("error"):
            event["status"] = "DECODE_ERROR"
            event["reason"] = decoded["error"]
        if event["event"] == "TokenLaunched" and event["source"] == "factory":
            args = decoded["args"]
            event["token"] = args["token"]
            event["curve"] = args["curve"]
            event["quote_asset"] = args["pairToken"]
        elif event["source"] == "factory" and "token" in (decoded.get("args") or {}):
            event["token"] = decoded["args"]["token"]
        if event["removed"]:
            event["status"] = "REMOVED"
            event["reason"] = "endpoint reported removed: true"
        return event


# --------------------------------------------------------------------------
# Finality (addendum 7)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Finality:
    """The measured block interval, and the depth it implies."""

    median_interval_s: float
    confirm_depth: int
    safe_tag_supported: bool
    sample: int

    def as_dict(self) -> dict:
        return {
            "median_block_interval_s": self.median_interval_s,
            "confirm_seconds": CONFIRM_SECONDS,
            "confirm_depth_blocks": self.confirm_depth,
            "safe_tag_supported": self.safe_tag_supported,
            "headers_sampled": self.sample,
            "rule": ("a block is confirmed when it is at least confirm_depth behind "
                     "head, and — when the endpoint answers the safe tag — also at "
                     "or below safe"),
        }


def measure_finality(headers, *, safe_tag_supported: bool,
                     confirm_seconds: int = CONFIRM_SECONDS) -> Finality:
    """Median block interval from observed headers; depth = 60 s of blocks.

    Measured, never remembered: Robinhood Chain is an Arbitrum Nitro chain and
    its interval is an operational fact of the day, not a constant we may
    quote from documentation.
    """
    times = sorted({int(h["number"]): int(h["timestamp"]) for h in headers}.items())
    if len(times) < 2:
        raise ValueError("need at least two headers to measure an interval")
    gaps = []
    for (n0, t0), (n1, t1) in zip(times, times[1:]):
        span = n1 - n0
        if span <= 0:
            continue
        gaps.append((t1 - t0) / span)
    if not gaps:
        raise ValueError("no positive block spans in the sample")
    median = statistics.median(gaps)
    depth = max(1, int(round(confirm_seconds / median))) if median > 0 else 1
    return Finality(median_interval_s=median, confirm_depth=depth,
                    safe_tag_supported=bool(safe_tag_supported), sample=len(times))


def is_confirmed(block_number: int, *, head: int, finality: Finality,
                 safe_block: int | None = None) -> bool:
    if head - int(block_number) < finality.confirm_depth:
        return False
    if finality.safe_tag_supported and safe_block is not None:
        return int(block_number) <= int(safe_block)
    return True


# --------------------------------------------------------------------------
# Curve state reads (addendum 6: lazy, once per curve, cached)
# --------------------------------------------------------------------------
def selector(signature: str) -> str:
    return keccak256_hex(signature.encode("ascii"))[:10]


#: The reads that make one calibrated initial state. Order fixed so the request
#: sequence is reproducible.
CURVE_READS: tuple[tuple[str, str], ...] = (
    ("getReserves", "getReserves()"),
    ("realQuoteReserve", "realQuoteReserve()"),
    ("sellableTokens", "sellableTokens()"),
    ("feeBps", "feeBps()"),
    ("creatorTaxBps", "creatorTaxBps()"),
    ("snipeTaxStartBps", "snipeTaxStartBps()"),
    ("snipeTaxSeconds", "snipeTaxSeconds()"),
    ("launchedAt", "launchedAt()"),
    ("graduated", "graduated()"),
)


def _decode_uint(payload: str, word: int = 0) -> int:
    data = bytes.fromhex(str(payload)[2:])
    return int.from_bytes(data[word * 32:(word + 1) * 32], "big")


def read_initial_state(rpc: RpcClient, curve: str, block: int, *,
                       cache: dict | None = None) -> tuple[CurveState, dict]:
    """Nine ``eth_call`` reads at the launch block, once per curve, then cached.

    Lazy on purpose (addendum 6): a curve that never reaches admission costs no
    state read at all, which is what keeps the request budget flat as the
    tracked set grows.
    """
    cache = cache if cache is not None else {}
    key = f"{str(curve).lower()}:{int(block)}"
    if key in cache:
        return cache[key]
    values: dict[str, object] = {}
    for name, signature in CURVE_READS:
        payload = rpc.call("eth_call", [{"to": str(curve).lower(),
                                         "data": selector(signature)}, hex(int(block))])
        if name == "getReserves":
            values["quoteReserve"] = _decode_uint(payload, 0)
            values["tokenReserve"] = _decode_uint(payload, 1)
        elif name == "graduated":
            values["graduated"] = bool(_decode_uint(payload))
        else:
            values[name] = _decode_uint(payload)
    state = CurveState(
        quote_reserve=int(values["quoteReserve"]),
        token_reserve=int(values["tokenReserve"]),
        real_quote_reserve=int(values["realQuoteReserve"]),
        sellable_tokens=int(values["sellableTokens"]),
        fee_bps=int(values["feeBps"]),
        creator_tax_bps=int(values["creatorTaxBps"]),
        snipe_tax_bps=0,
        graduated=bool(values["graduated"]))
    meta = {"snipe_start_bps": int(values["snipeTaxStartBps"]),
            "snipe_window_seconds": int(values["snipeTaxSeconds"]),
            "launched_at": int(values["launchedAt"]),
            "block": int(block), "curve": str(curve).lower()}
    cache[key] = (state, meta)
    return state, meta


# --------------------------------------------------------------------------
# The collector
# --------------------------------------------------------------------------
class Collector:
    """One process, one cursor, one normalisation path.

    ``tick()`` returns what it did; it never raises for an ordinary empty
    range. A budget stop propagates as :class:`flytrade.pons.budget.BudgetStop`
    *after* the cursor has been persisted, which is the whole point of
    persisting it before the risky call.
    """

    def __init__(self, rpc: RpcClient, manifest: Manifest, store: ChainStore, *,
                 finality: Finality, track_seconds: int = TRACK_SECONDS,
                 chunk_blocks: int = CHUNK_BLOCKS,
                 grid_blocks: int = HEADER_GRID_BLOCKS):
        self.rpc = rpc
        self.manifest = manifest
        self.store = store
        self.finality = finality
        self.track_seconds = int(track_seconds)
        self.chunk_blocks = int(chunk_blocks)
        self.grid = HeaderGrid(rpc, store, grid_blocks=grid_blocks,
                               interval_s=finality.median_interval_s)
        self.normalise = Normaliser(manifest)
        self.range_retreats: list[dict] = []
        self.quote_filter: str | None = None
        self.pending_curves: set[str] = set()
        self.launches: dict[str, dict] = {}
        self.completed: set[str] = set()
        self.held: set[str] = set()
        self.state_cache: dict = {}
        self.head: dict | None = None
        self.last_error: str | None = None
        self._restore()

    # ------------------------------------------------------------- restore
    def _restore(self) -> None:
        for event in self.store.live_events():
            if event.get("event") == "TokenLaunched" and event.get("source") == "factory":
                self._admit_launch(event)
            elif event.get("event") == "CurveCompleted" and event.get("curve"):
                self.completed.add(event["curve"])

    def _admit_launch(self, event: dict) -> None:
        curve = str(event.get("curve") or "").lower()
        if not curve:
            return
        args = event.get("args") or {}
        record = {
            "token": event.get("token"),
            "curve": curve,
            "deployment": event.get("deployment"),
            "quote_asset": str(event.get("quote_asset") or "").lower() or None,
            "launch_block": int(event["block_number"]),
            "launch_timestamp": int(event["block_timestamp"]),
            "launch_log_id": event["log_id"],
            "launch_config_id": args.get("launchConfigId"),
            "graduation_threshold": args.get("graduationThreshold"),
            "deployer": args.get("deployer"),
        }
        self.launches[curve] = record
        self.normalise.register_market(curve, record)

    # -------------------------------------------------------------- cursor
    @property
    def cursor_block(self) -> int | None:
        return None if self.store.cursor is None else int(self.store.cursor["block_number"])

    def tracked(self, now_ts: int) -> list[str]:
        """Curves launched inside the window, or held, minus the completed ones."""
        out = []
        for curve, record in self.launches.items():
            if curve in self.completed:
                continue
            if (self.quote_filter is not None
                    and record.get("quote_asset") != self.quote_filter):
                continue
            if curve in self.held or now_ts - record["launch_timestamp"] <= self.track_seconds:
                out.append(curve)
        return sorted(out)

    # ---------------------------------------------------------------- tick
    def tick(self, *, from_block: int | None = None) -> dict:
        """One poll: head, factory logs, tracked-curve logs, normalise, persist."""
        head = self.rpc.block("latest")
        self.head = head
        head_number = _int(head["number"])
        head_ts = _int(head["timestamp"])
        self.store.record_headers([head])
        start = from_block if from_block is not None else (
            (self.cursor_block or head_number) + 1)
        if start > head_number:
            self._persist_cursor(head_number, head["hash"], 0, 0, head_number)
            return {"from": start, "to": head_number, "events": 0, "requests": 1,
                    "reorg": False, "note": "no new blocks"}
        raws: list[dict] = []
        spent = self.rpc.ledger.attempts - 1
        chunk = self._tick_chunk(start, head_number)
        raws.extend(self.fetch_logs([self.manifest.factory.address], start,
                                    head_number, chunk=chunk, label="factory"))
        # A curve launched *inside this very range* has its opening trades in
        # the same range. Discovering it after the fact and waiting for the
        # next tick would step the cursor straight over them, so the address
        # list for the second query is the tracked set **plus** what the
        # factory logs just revealed. Still one query, whatever the count.
        discovered = []
        for raw in raws:
            if str(raw["address"]).lower() != self.manifest.factory.address:
                continue
            decoded = abi.decode_factory_log(raw)
            if decoded["event"] == "TokenLaunched":
                curve = str(decoded["args"]["curve"]).lower()
                if curve not in self.completed:
                    discovered.append(curve)
        addresses = sorted(set(self.tracked(head_ts)) | set(discovered))
        if addresses:
            raws.extend(self.fetch_logs(addresses, start, head_number,
                                        chunk=chunk, label="curves"))
        requests = self.rpc.ledger.attempts - spent
        return self._ingest(raws, head=head, start=start, requests=requests)

    def _tick_chunk(self, start: int, end: int) -> int:
        """One request per tick unless the span is large, then the donor's 25."""
        span = end - start + 1
        return span if span <= self.chunk_blocks * 4 else self.chunk_blocks

    # ------------------------------------------------- range retreat + logs
    def fetch_logs(self, addresses, lo: int, hi: int, *, chunk: int,
                   topics=None, label: str = "") -> list[dict]:
        """``eth_getLogs`` over ``[lo, hi]``, halving the chunk on a range refusal.

        Reviewer decision 1. ``RPC_RANGE_TOO_LARGE`` — the provider saying
        *this* request asked for too much, which dispatch 1's narrowed regex
        now separates from a spent quota — halves the chunk and retries the
        same span. It stops at :data:`MIN_CHUNK_BLOCKS` and then re-raises, so
        a range the endpoint will not serve at 25 blocks is a reported failure,
        not an unbounded retreat. **Every attempt, including the refused ones,
        is charged to the ledger** by the client before it raises; there is no
        other retry anywhere in this package.
        """
        addresses = [a.lower() for a in addresses]
        if not addresses or hi < lo:
            return []
        batches = [addresses[i:i + MAX_FILTER_ADDRESSES]
                   for i in range(0, len(addresses), MAX_FILTER_ADDRESSES)]
        out: list[dict] = []
        for batch in batches:
            size = max(MIN_CHUNK_BLOCKS, int(chunk))
            cursor = lo
            while cursor <= hi:
                top = min(cursor + size - 1, hi)
                try:
                    out.extend(self.rpc.logs(batch, cursor, top, topics))
                except RpcError as exc:
                    if exc.code != RANGE_TOO_LARGE:
                        raise
                    if size <= MIN_CHUNK_BLOCKS:
                        self.range_retreats.append(
                            {"label": label, "from": cursor, "to": top,
                             "chunk": size, "action": "stopped at the floor"})
                        raise
                    size = max(MIN_CHUNK_BLOCKS, size // 2)
                    self.range_retreats.append(
                        {"label": label, "from": cursor, "to": top,
                         "chunk": size, "action": "halved"})
                    continue
                cursor = top + 1
        return out

    # --------------------------------------------------------- confirmation
    def confirmation(self, block_number: int, *, head: int,
                     safe_block: int | None = None) -> dict:
        """Is ``block_number`` confirmed, and does its grid anchor still agree?

        Addendum 7 as amended by reviewer decision 2: the depth and ``safe``
        rules are unchanged, and the hash re-read that used to fetch the block
        itself now **re-reads the nearest grid header below it** and compares
        the answer with the header stored at scan time. One request. A
        disagreement is a reorg under the block in question and the caller must
        settle nothing.
        """
        confirmed = is_confirmed(block_number, head=head, finality=self.finality,
                                 safe_block=safe_block)
        anchor = self.store.header_at_or_below(int(block_number))
        out = {"block_number": int(block_number), "confirmed": bool(confirmed),
               "head": int(head), "safe_block": safe_block,
               "confirm_depth": self.finality.confirm_depth,
               "anchor": None if anchor is None else int(anchor["number"]),
               "anchor_hash_matches": None}
        if not confirmed or anchor is None:
            return out
        fresh = self.rpc.block(int(anchor["number"]))
        out["anchor_hash_matches"] = (
            str(fresh["hash"]).lower() == str(anchor["hash"]).lower())
        if not out["anchor_hash_matches"]:
            out["confirmed"] = False
            out["reason"] = "REORG_BELOW_BLOCK"
        return out

    # ------------------------------------------------------ bounded backfill
    def backfill_window(self, first_block: int, last_block: int, *,
                        factory_chunk: int = FACTORY_CHUNK_BLOCKS,
                        curve_chunk: int = CURVE_CHUNK_BLOCKS,
                        quote_asset: str | None = None,
                        on_segment=None) -> dict:
        """Collect ``[first_block, last_block]`` through the live tick's own path.

        Reviewer decision 1. The window is walked in factory-sized segments; in
        each, the factory filter runs first so a curve launched inside the
        segment is already in the address list when the curve filter runs over
        the same blocks. ``quote_asset`` restricts the tracked set (native ETH
        only this wave); launches on any other quote are still recorded and
        still get their ``DISCOVERY``, they are simply not followed.

        Stops cleanly on :class:`BudgetStop`, with the cursor already on disk.
        """
        self.quote_filter = None if quote_asset is None else str(quote_asset).lower()
        head = self.rpc.block("latest")
        self.head = head
        head_number = _int(head["number"])
        self.grid.ceiling = head_number
        summary = {"first_block": int(first_block), "last_block": int(last_block),
                   "segments": 0, "events": 0, "launches": 0,
                   "stopped": None, "reached": int(first_block) - 1}
        cursor = int(first_block)
        try:
            while cursor <= int(last_block):
                top = min(cursor + int(factory_chunk) - 1, int(last_block))
                self.grid.warm(cursor, top)
                raws = self.fetch_logs([self.manifest.factory.address], cursor, top,
                                       chunk=int(factory_chunk), label="factory")
                for raw in list(raws):
                    decoded = abi.decode_factory_log(raw)
                    if decoded["event"] != "TokenLaunched":
                        continue
                    curve = str(decoded["args"]["curve"]).lower()
                    pair = str(decoded["args"]["pairToken"]).lower()
                    if curve in self.completed:
                        continue
                    if self.quote_filter is not None and pair != self.quote_filter:
                        continue
                    self.pending_curves.add(curve)
                # the tracked window is measured against the *segment's* own
                # chain time, not against the live head: a backfill of blocks
                # from hours ago would otherwise find every curve aged out.
                segment_ts = self.grid.time(top).timestamp
                addresses = sorted(set(self.tracked(segment_ts))
                                   | self.pending_curves)
                if addresses:
                    raws.extend(self.fetch_logs(addresses, cursor, top,
                                                chunk=int(curve_chunk),
                                                label="curves"))
                result = self._ingest(raws, head=head, start=cursor, requests=0,
                                      cursor_block=top)
                summary["segments"] += 1
                summary["events"] += result["events"]
                summary["reached"] = top
                self.pending_curves = {c for c in self.pending_curves
                                       if c not in self.launches}
                if on_segment is not None:
                    on_segment(top, summary, self)
                cursor = top + 1
        except BudgetStop as stop:
            summary["stopped"] = stop.code
            summary["stop_detail"] = stop.detail
        except RpcError as exc:
            summary["stopped"] = exc.code
            summary["stop_detail"] = exc.detail
        summary["launches"] = len(self.launches)
        summary["complete"] = summary["reached"] >= int(last_block)
        return summary

    def _ranges(self, start: int, end: int):
        """One range per tick, chunked to the donor's 25 blocks only when large."""
        if end - start + 1 <= self.chunk_blocks * 4:
            return [(start, end)]
        out = []
        lo = start
        while lo <= end:
            hi = min(lo + self.chunk_blocks - 1, end)
            out.append((lo, hi))
            lo = hi + 1
        return out

    def ingest_raw(self, raws: list[dict], *, head: dict, start: int) -> dict:
        """Normalise and persist logs that arrived by some other route (tests)."""
        return self._ingest(raws, head=head, start=start, requests=0)

    def _ingest(self, raws: list[dict], *, head: dict, start: int,
                requests: int, cursor_block: int | None = None) -> dict:
        head_number = _int(head["number"])
        received_at = _now_iso()
        # Out-of-order delivery is not an error; it is sorted before anything
        # else looks at it. Duplicates across ticks collapse on the log id.
        ordered = sorted(raws, key=order_key)
        deduped: dict[str, dict] = {}
        for raw in ordered:
            ident = log_id(raw)
            previous = deduped.get(ident)
            if previous is not None and previous != raw and not raw.get("removed"):
                raise RpcError("CONFLICTING_DUPLICATE_LOG", ident)
            deduped[ident] = raw
        ordered = sorted(deduped.values(), key=order_key)
        self.store.record_raw(ordered, received_at=received_at)

        removed = [r for r in ordered if r.get("removed")]
        reorg = bool(removed)
        orphaned: list[str] = []
        if removed:
            blocks = {_int(r["blockNumber"]) for r in removed}
            hashes = {str(r["blockHash"]).lower() for r in removed}
            victims = [e["log_id"] for e in self.store.events
                       if int(e["block_number"]) in blocks
                       or str(e["block_hash"]).lower() in hashes]
            victims.extend(log_id(r) for r in removed)
            orphaned = self.store.orphan(victims, at_block=head_number,
                                         reason="removed log")
            self._rewind(min(blocks))

        times = self._times_for(ordered, head)
        events = []
        for raw in ordered:
            if raw.get("removed"):
                continue
            header = times[str(raw["blockHash"]).lower()]
            event = self.normalise(raw, header)
            events.append(event)
            if event["event"] == "TokenLaunched" and event["source"] == "factory":
                self._admit_launch(event)
            if event["event"] == "CurveCompleted" and event.get("curve"):
                self.completed.add(event["curve"])
        # A second pass: a curve launched inside this very batch has its own
        # later logs in the same batch, and they must not be left unknown.
        rerun = [e for e in events
                 if e["status"] == "UNKNOWN_SOURCE" and e["address"] in self.launches]
        if rerun:
            by_id = {e["log_id"]: e for e in events}
            for stale in rerun:
                raw = deduped[stale["log_id"]]
                header = times[str(raw["blockHash"]).lower()]
                by_id[stale["log_id"]] = self.normalise(raw, header)
            events = [by_id[e["log_id"]] for e in events]
            for event in events:
                if event["event"] == "CurveCompleted" and event.get("curve"):
                    self.completed.add(event["curve"])
        self.store.record_events(events)
        last = events[-1] if events else None
        at = head_number if cursor_block is None else int(cursor_block)
        at_hash = (str(head["hash"]).lower() if cursor_block is None
                   else str((self.store.headers_by_number.get(at) or {}).get("hash", "")))
        self._persist_cursor(
            at, at_hash,
            last["tx_index"] if last else 0, last["log_index"] if last else 0,
            head_number)
        return {"from": start, "to": at, "events": len(events),
                "requests": requests, "reorg": reorg, "orphaned": orphaned,
                "tracked": len(self.tracked(_int(head["timestamp"])))}

    def _times_for(self, raws: list[dict], head: dict) -> dict:
        """A :class:`BlockTime` per delivered log, off the sparse grid.

        Reviewer decision 2. A grid anchor whose stored hash disagrees with a
        log delivered for that very block number is a reorg during the scan and
        is refused; between anchors the log's own ``blockHash`` is the anchor
        and the timestamp is interpolated with its precision recorded.
        """
        self.grid.ceiling = _int(head["number"])
        times: dict[str, BlockTime] = {}
        for raw in raws:
            key = str(raw["blockHash"]).lower()
            if key in times:
                continue
            number = _int(raw["blockNumber"])
            known = self.store.headers_by_number.get(number)
            if known is not None and str(known["hash"]).lower() != key:
                raise RpcError("REORG_DURING_SCAN", key)
            time = self.grid.time(number)
            if time.block_hash and str(time.block_hash).lower() != key:
                raise RpcError("REORG_DURING_SCAN", key)
            times[key] = time
        return times

    def _rewind(self, block_number: int) -> None:
        target = max(0, int(block_number) - 1)
        confirmed = self.store.cursor.get("confirmed_block") if self.store.cursor else None
        block_hash = ""
        header = self.store.headers_by_number.get(target)
        if header is not None:
            block_hash = header["hash"]
        self.store.save_cursor(
            chain_id=self.manifest.chain_id, block_number=target,
            block_hash=block_hash, tx_index=0, log_index=0,
            confirmed_block=confirmed,
            confirmed_hash=self.store.cursor.get("confirmed_hash") if self.store.cursor else None)

    def _persist_cursor(self, block_number: int, block_hash: str, tx_index: int,
                        log_index: int, head_number: int) -> None:
        confirmed = max(0, head_number - self.finality.confirm_depth)
        header = self.store.header_at_or_below(confirmed)
        self.store.save_cursor(
            chain_id=self.manifest.chain_id, block_number=block_number,
            block_hash=block_hash, tx_index=tx_index, log_index=log_index,
            confirmed_block=confirmed,
            confirmed_hash=None if header is None else header["hash"])

    # ------------------------------------------------------------- backfill
    def backfill_start(self, head_number: int, head_timestamp: int) -> int:
        """The first block of a bounded live backfill: at most one hour of them."""
        blocks = max(1, int(round(BACKFILL_SECONDS / self.finality.median_interval_s)))
        return max(0, head_number - blocks)

    def block_lag(self) -> dict:
        if self.head is None or self.store.cursor is None:
            return {"blocks": None, "seconds": None}
        head_number = _int(self.head["number"])
        head_ts = _int(self.head["timestamp"])
        cursor_block = int(self.store.cursor["block_number"])
        header = self.store.headers_by_number.get(cursor_block)
        return {"blocks": head_number - cursor_block,
                "seconds": None if header is None else head_ts - int(header["timestamp"])}


__all__ = ["Collector", "Normaliser", "Finality", "measure_finality", "is_confirmed",
           "read_initial_state", "selector", "CollectorStop", "BudgetStop",
           "BlockTime", "HeaderGrid", "BlockClock", "CHUNK_BLOCKS",
           "MIN_CHUNK_BLOCKS",
           "HEADER_GRID_BLOCKS", "FACTORY_CHUNK_BLOCKS", "CURVE_CHUNK_BLOCKS",
           "MAX_FILTER_ADDRESSES", "BACKFILL_SECONDS", "CONFIRM_SECONDS",
           "TRACK_SECONDS"]
