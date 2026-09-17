#!/usr/bin/env python
"""What `run.py`, `grid.py` and `evaluate.py` share: the split, the brain and
the evaluator-only label.

**Nothing in this module opens a socket.** It reads
``data/pons/d11-backfill-v1`` and the two committed configurations, and it
computes the registered split from timestamps alone. A test parses it, and
``grid.py`` and ``evaluate.py``, for network verbs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "upstream"))
sys.path.insert(0, str(HERE))

from flytrade import decoder as D                       # noqa: E402
from flytrade import graph as G                         # noqa: E402
from flytrade import mushroom as M                      # noqa: E402
from flytrade import populations as P                   # noqa: E402
from flytrade import readout as RO                      # noqa: E402
from flytrade import runner as R                        # noqa: E402
from flytrade import state as S                         # noqa: E402
from flytrade.pons import paper as PAPER                # noqa: E402
from flytrade.pons.admission_v2 import AdmissionPolicyV2  # noqa: E402
from flytrade.pons.collector import BlockClock          # noqa: E402
from flytrade.pons.context_v2 import context_v2         # noqa: E402
from flytrade.pons.encoder_v2 import SensoryEncoderV2   # noqa: E402

D10 = ROOT / "experiments" / "d10"
DATA = ROOT / "data" / "malecns-v1.0"
DATASET = ROOT / "data" / "pons" / "d11-backfill-v1"
RUNS = HERE / "runs"
RUN_ID = "d11-001"

CONFIG_V2 = HERE / "config.json"          # the D11 environment: v2 numbers
CONFIG_RUN = HERE / "d11_001.json"        # this run's registration

CADENCE = 30
LATENCY_S = 2
HORIZON_S = 900
#: latency + horizon + one tick: the slot one episode occupies on the grid.
SLOT_S = LATENCY_S + HORIZON_S + CADENCE
SETTLE_S = LATENCY_S + HORIZON_S


def configs() -> tuple[dict, dict]:
    return json.loads(CONFIG_V2.read_text()), json.loads(CONFIG_RUN.read_text())


def manifest() -> dict:
    return json.loads((DATASET / "MANIFEST.json").read_text())


# --------------------------------------------------------------- the split
def split(window: dict | None = None) -> dict:
    """The registered 70/30 temporal split, from timestamps and nothing else.

    ``t0`` and ``t1`` are the window's first and last block timestamps;
    ``T = t0 + floor(0.7 * (t1 - t0))`` snapped **down** to the 30-second tick
    grid anchored at ``t0``. One grid serves every partition, every replay
    branch and the evaluation, so a cutoff is the same instant everywhere.
    """
    window = window or manifest()["window"]
    t0 = int(window["first_ts"])
    t1 = int(window["last_ts"])
    # floor(0.7 * span) in INTEGER arithmetic. `0.7 * 43200` is
    # 30239.999999999996 in float64 and its floor is 30239, which is a
    # property of binary floating point and not of the registered rule; the
    # rule is a rational one and is computed as one.
    raw = t0 + (7 * (t1 - t0)) // 10
    T = t0 + ((raw - t0) // CADENCE) * CADENCE
    learning = list(range(t0, T + 1, CADENCE))
    first_frozen = t0 + -(-(T - t0) // CADENCE) * CADENCE      # ceil to the grid
    frozen = [c for c in range(first_frozen, t1 + 1, CADENCE)
              if c >= T and c + SETTLE_S <= t1]
    last_learning_entry = None
    for c in learning:
        if c + SETTLE_S <= T:
            last_learning_entry = c
    blocks = []
    if frozen:
        span = frozen[-1] - frozen[0]
        edges = [frozen[0] + round(span * i / 3.0) for i in range(4)]
        for i in range(3):
            lo, hi = edges[i], edges[i + 1]
            rows = [c for c in frozen if (lo <= c < hi) or (i == 2 and c == hi)]
            blocks.append({"block": i + 1, "from_ts": lo, "to_ts": hi,
                           "ticks": len(rows),
                           "first_tick": rows[0] if rows else None,
                           "last_tick": rows[-1] if rows else None})
    return {
        "rule": ("t0 = timestamp(start_block), t1 = timestamp(end_block), "
                 "T = t0 + floor(0.7 * (t1 - t0)) snapped down to the "
                 "30-second tick grid anchored at t0"),
        "t0": t0, "t1": t1, "T": T,
        "span_s": t1 - t0,
        "learning_share": (T - t0) / (t1 - t0) if t1 > t0 else 0.0,
        "cadence_s": CADENCE, "latency_s": LATENCY_S, "horizon_s": HORIZON_S,
        "settle_s": SETTLE_S, "slot_s": SLOT_S,
        "learning_ticks": len(learning),
        "learning_first_tick": learning[0] if learning else None,
        "learning_last_tick": learning[-1] if learning else None,
        "learning_last_entry_tick": last_learning_entry,
        "learning_entry_rule": "an entry is allowed only if cutoff + 902 <= T",
        "frozen_ticks": len(frozen),
        "frozen_first_tick": frozen[0] if frozen else None,
        "frozen_last_tick": frozen[-1] if frozen else None,
        "frozen_tick_rule": "T <= cutoff and cutoff + 902 <= t1",
        "temporal_blocks": blocks,
    }


def block_of(cutoff: int, blocks: list[dict]) -> int | None:
    """Which temporal block a frozen cutoff falls in. The last closes right."""
    for row in blocks:
        if row["from_ts"] <= int(cutoff) < row["to_ts"]:
            return int(row["block"])
    if blocks and int(cutoff) == blocks[-1]["to_ts"]:
        return int(blocks[-1]["block"])
    return None


def geometric_ceiling(first_eligible_tick: int | None, T: int) -> dict:
    """Non-overlapping 932-second slots between the first eligible tick and T-902."""
    last = int(T) - SETTLE_S
    if first_eligible_tick is None or last < int(first_eligible_tick):
        return {"ceiling": 0, "first_eligible_tick": first_eligible_tick,
                "last_entry_tick": last, "slot_s": SLOT_S}
    span = last - int(first_eligible_tick)
    return {"ceiling": int(span // SLOT_S) + 1,
            "first_eligible_tick": int(first_eligible_tick),
            "last_entry_tick": last, "span_s": span, "slot_s": SLOT_S,
            "rule": ("the number of non-overlapping 932-second slots (902 s "
                     "plus one tick) between the first LEARNING tick with at "
                     "least one v2-eligible candidate and T - 902")}


# ---------------------------------------------------------------- the brain
def build_brain(cfg_v2: dict):
    """The clean reference brain under ``pons_encoder_v2``. No socket, no run."""
    import flysim
    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    sha = G.sha256_file(DATA / "graph.npz")
    want = cfg_v2["next_run"]["clean_reference_checkpoint"]["graph_sha256"]
    if sha != want:
        raise SystemExit(f"graph sha256 {sha[:12]} != the pre-registered "
                         f"{want[:12]}: the run is refused")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    enc = cfg_v2["encoder"]
    encoder = SensoryEncoderV2(
        ann, cfg_v2["features"]["scales"],
        features=tuple(cfg_v2["features"]["order"]),
        carrier=float(enc["carrier"]),
        drive_budget_hz=float(enc["drive_budget_hz"]),
        drive_max_hz=float(enc["drive_max_hz"]),
        coding=str(enc["coding"]))
    if list(encoder.features) != list(cfg_v2["features"]["order"]):
        raise SystemExit("the encoder dropped a feature the config registered")
    if encoder.input_schema_sha256 != enc["input_schema_sha256"]:
        raise SystemExit(
            f"the encoder's input schema {encoder.input_schema_sha256[:12]} is "
            f"not the registered {enc['input_schema_sha256'][:12]}")
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, encoder.olfactory, pops, graph_sha256=sha)
    clean = S.learned_state_digest(mb.gain, mb.pos, sha)
    want_dig = cfg_v2["next_run"]["clean_reference_checkpoint"]["state_digest"]
    if clean != want_dig:
        raise SystemExit(f"clean reference digest {clean[:12]} != the "
                         f"pre-registered {want_dig[:12]}: the run is refused")
    return fb, mb, ann, encoder, pops, run, sha, clean


def admission_v2(cfg_v2: dict, *, require_coverage: bool = True,
                 max_candidates: int | None = None) -> AdmissionPolicyV2:
    c = cfg_v2["admission"]["constants"]
    return AdmissionPolicyV2(
        size_wei=int(10 ** 16), latency_s=LATENCY_S, horizon_s=HORIZON_S,
        max_candidates=(int(cfg_v2["admission"]["max_candidates_per_round"])
                        if max_candidates is None else int(max_candidates)),
        require_coverage=require_coverage,
        recent_window_s=int(c["recent_window_seconds"]),
        min_valid_trades_in_window=int(c["minimum_valid_trades_in_window"]),
        max_seconds_since_last_trade=int(c["maximum_seconds_since_last_trade"]))


def block_clock(directory: Path | None = None) -> BlockClock:
    """The store's own header grid. Reads files; opens nothing."""
    directory = Path(directory or DATASET)
    man = json.loads((directory / "MANIFEST.json").read_text())
    headers = [json.loads(line) for line
               in (directory / "headers.jsonl").read_text().splitlines()
               if line.strip()]
    return BlockClock(headers,
                      interval_s=float(man["window"]["median_block_interval_s"]),
                      grid_blocks=int(man["header_grid_blocks"]))


# ----------------------------------------------- the evaluator-only label
#: what the label says when the exit could not be priced at all
UNRESOLVED = "UNRESOLVED"


def gas_constants(cfg_run: dict) -> dict:
    g = cfg_run["fixed_for_the_whole_wave"]["gas_wei"]
    return {"gas_buy_wei": int(g["buy"]), "gas_sell_wei": int(g["sell"]),
            "gas_approval_wei": int(g["approval"])}


def label_row(tape, cutoff: int, clock, *, size_wei: int = 10 ** 16,
              gas: dict | None = None) -> dict:
    """The evaluator-only fixed-15-minute net outcome of one (tape, cutoff).

    A hypothetical buy of ``size_wei`` at ``cutoff + 2 s`` through
    :meth:`flytrade.pons.paper.PonsPaperExecution.plan_buy` on a **fresh**
    execution object, the position's own reserve delta carried exactly as the
    loop's settlement path carries it, and the exit priced by ``plan_sell`` on
    the tape advanced by the recorded external events at
    ``entry_fill_block_timestamp + 900 s``. ``net`` is computed by the same
    arithmetic :meth:`flytrade.execution.ExecutionPolicy._settle` uses, so it
    reproduces a recorded episode's ``net_pnl`` bit for bit.

    **It creates no trade, alters no bankroll, produces no reinforcement and
    touches neither ledger nor checkpoint.** An ``Unresolved`` (route
    transition, coverage, an exhausted curve) is reported as ``UNRESOLVED``
    and is excluded from the AUC rather than scored as a loss.
    """
    gas = gas or {}
    x = PAPER.PonsPaperExecution(size_wei=int(size_wei), latency_s=LATENCY_S,
                                 horizon_s=HORIZON_S, **gas)
    out = {"cutoff_ts": int(cutoff), "token": tape.token, "curve": tape.curve,
           "settled": False, "status": UNRESOLVED, "reason": "", "net": None,
           "positive": None}
    try:
        buy = x.plan_buy(tape, int(cutoff), clock)
    except PAPER.Unresolved as exc:
        out["reason"] = f"{exc.reason}:BUY"
        return out
    # the loop's own carry: the exit quote sees our impact plus external flow
    x.own_delta[tape.curve] = {"quote": buy.quote.net_into_curve,
                               "tokens": buy.quote.tokens_out}
    horizon_ts = int(buy.block_timestamp) + HORIZON_S
    try:
        sell = x.plan_sell(tape, horizon_ts, buy.quantity, clock,
                           tokens_wei=buy.quote.tokens_out)
    except PAPER.Unresolved as exc:
        out["reason"] = f"{exc.reason}:SELL"
        return out
    gross = buy.quantity * (sell.fill_price - buy.fill_price)
    fees = buy.fee + sell.fee
    net = gross - fees
    # the same quantities in wei, exactly as the curve handed them over, so a
    # reader can check `quote_out - spent - gas` against the float above
    # without re-deriving anything: net is a float of an integer answer.
    gas_total = x.gas_buy_wei + x.gas_sell_wei + x.gas_approval_wei
    net_wei = int(sell.quote.quote_out) - int(buy.quote.spent) - int(gas_total)
    out.update({
        "tokens_out_wei": str(int(buy.quote.tokens_out)),
        "spent_wei": str(int(buy.quote.spent)),
        "net_into_curve_wei": str(int(buy.quote.net_into_curve)),
        "quote_out_wei": str(int(sell.quote.quote_out)),
        "gross_quote_out_wei": str(int(sell.quote.gross_quote_out)),
        "gas_total_wei": str(int(gas_total)),
        "net_wei": str(int(net_wei)),
        "net_from_wei_eth": net_wei / PAPER.WEI,
        "settled": True, "status": "SETTLED", "net": float(net),
        "positive": bool(net > 0),
        "gross_pnl": float(gross), "fees": float(fees),
        "quantity": float(buy.quantity),
        "entry_block": int(buy.block_number), "entry_ts": int(buy.block_timestamp),
        "exit_block": int(sell.block_number), "exit_ts": int(sell.block_timestamp),
        "entry_fill_price": float(buy.fill_price),
        "exit_fill_price": float(sell.fill_price),
        "horizon_ts": horizon_ts,
        "return_on_notional": float(net / (int(size_wei) / PAPER.WEI)),
    })
    return out


# ------------------------------------------------------------- saturation
#: where the encoder's clip bites (flytrade/encoder.py: np.clip(u, -1, 1))
SATURATION_EPS = 1e-12


def saturated(normalised) -> np.ndarray:
    u = np.asarray(normalised, dtype=np.float64)
    return np.abs(u) >= 1.0 - SATURATION_EPS


__all__ = ["ROOT", "HERE", "DATASET", "RUNS", "RUN_ID", "CADENCE", "LATENCY_S",
           "HORIZON_S", "SLOT_S", "SETTLE_S", "configs", "manifest", "split",
           "block_of", "geometric_ceiling", "build_brain", "admission_v2",
           "block_clock", "label_row", "saturated", "SATURATION_EPS",
           "UNRESOLVED", "gas_constants", "context_v2", "RO", "D", "S", "R"]
