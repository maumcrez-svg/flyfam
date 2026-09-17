"""A **scripted RPC endpoint**. Every number in this module is invented.

Nothing here is an observation. The block hashes, timestamps, token addresses
and trade amounts are constructed so a test can ask for a gap, a duplicate, an
out-of-order delivery, a ``removed: true`` log or a two-block reorg at a chosen
moment — none of which a real endpoint will produce on demand. No figure
produced by this module may ever be reported as a measurement of Robinhood
Chain or of PONS.

What is real in the tests that use it: the whole of
:class:`flytrade.pons.rpc.RpcClient` above the socket — the method allowlist,
the JSON-RPC envelope checks, the masking, the request ledger and its archive
weighting — plus the real :class:`flytrade.pons.collector.Collector`, the real
:class:`flytrade.pons.storage.ChainStore` on a real temporary directory, and
the real hand decoder. Only the bytes on the wire are scripted, through the
``opener`` seam the client already has.
"""

from __future__ import annotations

import json

from flytrade.pons import abi

CHAIN_ID = 4663
FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
CURVE = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"
BUYER = "0x3333333333333333333333333333333333333333"
NATIVE = "0x" + "0" * 40


def word(value) -> str:
    if isinstance(value, str):
        return value.lower().replace("0x", "").rjust(64, "0")
    if isinstance(value, bool):
        return ("1" if value else "0").rjust(64, "0")
    return format(int(value), "064x")


def topic(value) -> str:
    return "0x" + word(value)


def block_hash(number: int, fork: str = "a") -> str:
    return "0x" + (f"{fork}{number:07d}").encode().hex().rjust(64, "0")


def tx_hash(number: int, index: int, fork: str = "a") -> str:
    return "0x" + (f"t{fork}{number:05d}{index:02d}").encode().hex().rjust(64, "0")


def make_log(*, address, event: abi.Event, indexed, data_values, block: int,
             tx_index: int = 0, log_index: int = 0, fork: str = "a",
             removed: bool = False) -> dict:
    return {
        "address": address.lower(),
        "blockHash": block_hash(block, fork),
        "blockNumber": hex(block),
        "transactionHash": tx_hash(block, tx_index, fork),
        "transactionIndex": hex(tx_index),
        "logIndex": hex(log_index),
        "topics": [event.topic0] + [topic(v) for v in indexed],
        "data": "0x" + "".join(word(v) for v in data_values),
        "removed": removed,
    }


def factory_event(name: str) -> abi.Event:
    return next(e for e in abi.V2_FACTORY_EVENTS if e.name == name)


def curve_event(name: str) -> abi.Event:
    return next(e for e in abi.CURVE_EVENTS if e.name == name)


def launch_log(block: int = 101, fork: str = "a", **kw) -> dict:
    return make_log(address=FACTORY, event=factory_event("TokenLaunched"),
                    indexed=[TOKEN, CURVE, BUYER],
                    data_values=[NATIVE, 1, 4_200_000_000_000_000_000],
                    block=block, fork=fork, **kw)


def buy_log(block: int, quote_in: int, tokens_out: int, fee: int, tax: int,
            *, fork: str = "a", log_index: int = 0, tx_index: int = 0,
            removed: bool = False) -> dict:
    return make_log(address=CURVE, event=curve_event("CurveBuy"),
                    indexed=[BUYER, BUYER],
                    data_values=[quote_in, tokens_out, fee, tax],
                    block=block, fork=fork, log_index=log_index,
                    tx_index=tx_index, removed=removed)


def sell_log(block: int, tokens_in: int, quote_out: int, fee: int, tax: int,
             *, fork: str = "a", log_index: int = 0, tx_index: int = 0) -> dict:
    return make_log(address=CURVE, event=curve_event("CurveSell"),
                    indexed=[BUYER, BUYER],
                    data_values=[tokens_in, quote_out, fee, tax],
                    block=block, fork=fork, log_index=log_index,
                    tx_index=tx_index)


class ScriptedEndpoint:
    """A fake node. It answers the six allowed methods and nothing else.

    ``faults`` turns on the behaviours a real endpoint will not perform to
    order: ``duplicate`` returns every log twice, ``shuffle`` returns them in
    reverse chain order, ``http_429`` answers one request with HTTP 429,
    ``quota`` answers one request with a provider quota message, and
    ``fail_after`` makes every call past that count a transport failure.
    """

    def __init__(self, *, logs=None, head: int = 110, first: int = 100,
                 timestamps=None, chain_id: int = CHAIN_ID, code: dict | None = None,
                 faults=(), fork: str = "a"):
        self.logs = list(logs or [])
        self.head = head
        self.first = first
        self.chain_id = chain_id
        self.code = dict(code or {})
        self.faults = set(faults)
        self.fork = fork
        self.timestamps = dict(timestamps or {})
        self.calls: list[tuple[str, list]] = []
        self.fail_after: int | None = None

    # ------------------------------------------------------------ helpers
    def header(self, number: int) -> dict:
        number = int(number)
        return {"number": hex(number), "hash": block_hash(number, self.fork),
                "parentHash": block_hash(number - 1, self.fork),
                "timestamp": hex(self.timestamps.get(number, 1_700_000_000 + number))}

    def add(self, *logs) -> None:
        self.logs.extend(logs)

    # ------------------------------------------------------------- opener
    def __call__(self, url, body, timeout):
        request = json.loads(body)
        method, params = request["method"], request["params"]
        self.calls.append((method, params))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise OSError("scripted transport failure")
        if "http_429" in self.faults:
            self.faults.discard("http_429")
            return 429, b'{"error":"too many requests"}'
        if "quota" in self.faults:
            self.faults.discard("quota")
            return 200, json.dumps({
                "jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32005, "message": "monthly quota exceeded"}}).encode()
        result = self.dispatch(method, params)
        if isinstance(result, dict) and "__error__" in result:
            return 200, json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                    "error": result["__error__"]}).encode()
        return 200, json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                "result": result}).encode()

    def dispatch(self, method: str, params: list):
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag == "latest":
                return self.header(self.head)
            if tag == "safe":
                if "no_safe_tag" in self.faults:
                    return {"__error__": {"code": -32602, "message": "unknown block"}}
                return self.header(max(self.first, self.head - 5))
            return self.header(int(str(tag), 16))
        if method == "eth_getCode":
            return self.code.get(str(params[0]).lower(), "0x")
        if method == "eth_call":
            return "0x" + word(0)
        if method == "eth_getLogs":
            criteria = params[0]
            lo = int(str(criteria["fromBlock"]), 16)
            hi = int(str(criteria["toBlock"]), 16)
            wanted = {a.lower() for a in criteria["address"]}
            topics = criteria.get("topics")
            out = []
            for log in self.logs:
                number = int(str(log["blockNumber"]), 16)
                if not (lo <= number <= hi) or log["address"] not in wanted:
                    continue
                if topics and topics[0] and log["topics"][0] != topics[0]:
                    continue
                out.append(dict(log))
            if "duplicate" in self.faults:
                out = out + [dict(entry) for entry in out]
            if "shuffle" in self.faults:
                out = list(reversed(out))
            return out
        raise AssertionError(f"scripted endpoint asked for {method}")  # pragma: no cover


class TickingEndpoint(ScriptedEndpoint):
    """A scripted endpoint whose head advances with a clock. **Invented too.**

    The live driver polls on the wall clock, so a test of it needs a chain that
    moves while the test waits. This one produces one block per second from the
    moment it is built, and stamps each block with the real second it would
    have happened at, so chain time and the driver's clock agree. It is still a
    fixture: no number it returns is an observation of anything.

    ``clock`` is the driver's own ``now`` callable, so an in-process test can
    drive it with a fake clock and a subprocess test with ``time.time``.
    """

    def __init__(self, *, clock=None, blocks_per_second: float = 1.0, **kw):
        import time as _time
        self._clock = clock or _time.time
        self._per_second = float(blocks_per_second)
        self._base = int(kw.get("head", 110))
        self._epoch = int(self._clock())
        super().__init__(**kw)

    @property
    def head(self) -> int:
        return self._base + int((self._clock() - self._epoch) * self._per_second)

    @head.setter
    def head(self, value) -> None:
        self._base = int(value)
        self._epoch = int(self._clock())

    def header(self, number: int) -> dict:
        number = int(number)
        stamp = self._epoch + int(round((number - self._base) / self._per_second))
        return {"number": hex(number), "hash": block_hash(number, self.fork),
                "parentHash": block_hash(number - 1, self.fork),
                "timestamp": hex(self.timestamps.get(number, stamp))}
