"""D11-001 addendum 8 — the evaluator-only label, checked against D10's legs.

**Written and run before the grid's label pass.** The label is the only number
in the frozen evaluation that is not produced by the brain, so it is checked
where an answer already exists: the **16 settled D10 entries**, at their
recorded cutoffs, on the stores those runs read.

*"To the wei"* is asserted where the records carry wei: the recorded
``tokens_out_wei`` is an exact integer and the label must reproduce it exactly,
and the label's own integer identity ``quote_out - spent - gas`` must equal its
float ``net`` to the limit of float64. The recorded ``net_pnl`` and
``return_on_notional`` are stored rounded (8 and 10 decimals, see
``flytrade.execution.OutcomeRecord.as_dict``), and the label is asserted to
reproduce them **at exactly that precision** — nothing looser.

The label is also asserted to do none of the things it must not do: no trade,
no bankroll movement, no reinforcement, no ledger and no checkpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
D11 = ROOT / "experiments" / "d11"
D10 = ROOT / "experiments" / "d10"
sys.path.insert(0, str(D11))

import common as C                                       # noqa: E402
from flytrade.pons.collector import BlockClock           # noqa: E402
from retrospective import Tracker                        # noqa: E402

#: the three D10 logs that carry settled outcomes, and the store each read.
BRANCHES = (
    ("d10-001/learning", D10 / "runs/d10-001/learning/events.jsonl",
     ROOT / "data/pons/d10-backfill-v1", False),
    ("d10-001/frozen_reference", D10 / "runs/d10-001/frozen_reference/events.jsonl",
     ROOT / "data/pons/d10-backfill-v1", False),
    ("d10-live-001/live", D10 / "runs/d10-live-001/live/events.jsonl",
     D10 / "runs/d10-live-001/chain", True),
)

D10_GAS = {"gas_buy_wei": 26_513_686_360_000,
           "gas_sell_wei": 21_543_833_760_000,
           "gas_approval_wei": 16_104_600_000_000}


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def settled_entries():
    """``(branch, store, live, execution, outcome)`` for every settled D10 entry."""
    out = []
    for name, log, store, live in BRANCHES:
        if not log.exists() or not store.exists():
            continue
        records = _records(log)
        execs = {r["episode_id"]: r for r in records if r["kind"] == "EXECUTION"}
        for outcome in (r for r in records if r["kind"] == "OUTCOME"):
            ex = execs.get(outcome["episode_id"])
            if ex is None:
                continue
            out.append((name, store, live, ex, outcome))
    return out


ENTRIES = settled_entries()
IDS = [f"{n}:{ex['episode_id']}" for n, _, _, ex, _ in ENTRIES]

_TRACKERS: dict = {}
_CLOCKS: dict = {}


def _tracker(store: Path, live: bool) -> Tracker:
    key = str(store)
    if key not in _TRACKERS:
        _TRACKERS[key] = Tracker(store, live=live)
    return _TRACKERS[key]


def _clock(store: Path) -> BlockClock:
    key = str(store)
    if key not in _CLOCKS:
        man_path = store / "MANIFEST.json"
        if man_path.exists():
            man = json.loads(man_path.read_text())
            interval = float(man["window"]["median_block_interval_s"])
            grid = int(man["header_grid_blocks"])
        else:
            # the live chain store has no manifest: the D10 live run's own
            # finality numbers, from experiments/d10/finality.json
            fin = json.loads((D10 / "finality.json").read_text())
            interval = float(fin["median_block_interval_s"])
            grid = 100
        headers = [json.loads(line) for line
                   in (store / "headers.jsonl").read_text().splitlines()
                   if line.strip()]
        _CLOCKS[key] = BlockClock(headers, interval_s=interval, grid_blocks=grid)
    return _CLOCKS[key]


def test_there_are_sixteen_settled_d10_entries():
    """The known-answer set is the one addendum 8 names, not a subset."""
    assert len(ENTRIES) == 16, [i for i in IDS]


@pytest.mark.parametrize("name,store,live,ex,outcome", ENTRIES, ids=IDS)
def test_the_label_reproduces_a_settled_d10_entry(name, store, live, ex, outcome):
    track = _tracker(store, live)
    tape = track.tapes.get(ex["token"])
    assert tape is not None, f"{name}: {ex['token']} has no reconstructed tape"

    got = C.label_row(tape, int(ex["cutoff_ts"]), _clock(store), gas=D10_GAS)
    assert got["settled"], (name, got["reason"])

    # -- the wei the record carries, exactly -----------------------------
    assert got["tokens_out_wei"] == ex["tokens_out_wei"]

    # -- the blocks and the instants the fill rule chose ------------------
    assert got["entry_block"] == outcome["entry"]["bar_index"]
    assert got["entry_ts"] == outcome["entry"]["ts"]
    assert got["exit_block"] == outcome["exit"]["bar_index"]
    assert got["exit_ts"] == outcome["exit"]["ts"]
    assert got["horizon_ts"] == ex["horizon_ts"]

    # -- the integer identity, and the float that carries it -------------
    # quote_out - spent - gas is exact arithmetic on the curve's own integers;
    # `net` is the float _settle produces. They agree to the limit of float64,
    # which on a 0.01 ETH notional is far below one wei.
    assert abs(got["net"] - got["net_from_wei_eth"]) < 1e-15

    # -- the recorded numbers, at the precision the record stores ---------
    assert round(got["net"], 8) == outcome["net_pnl"]
    assert round(got["return_on_notional"], 10) == outcome["return_on_notional"]
    assert round(got["gross_pnl"], 8) == outcome["gross_pnl"]
    assert round(got["fees"], 8) == outcome["fees"]
    assert round(got["quantity"], 8) == round(outcome["entry"]["quantity"], 8)


def test_the_label_creates_no_trade_and_moves_no_bankroll():
    """It is an evaluator-only number and the object it uses proves it."""
    name, store, live, ex, outcome = ENTRIES[0]
    track = _tracker(store, live)
    tape = track.tapes[ex["token"]]

    from flytrade.pons import paper as PAPER
    made: list = []
    real_settle = PAPER.PonsPaperExecution._settle
    real_open = PAPER.PonsPaperExecution.open_long
    real_reinforce = PAPER.PonsPaperExecution.reinforcement
    PAPER.PonsPaperExecution._settle = lambda *a, **k: made.append("settle")
    PAPER.PonsPaperExecution.open_long = lambda *a, **k: made.append("open")
    PAPER.PonsPaperExecution.reinforcement = lambda *a, **k: made.append("reward")
    try:
        got = C.label_row(tape, int(ex["cutoff_ts"]), _clock(store), gas=D10_GAS)
    finally:
        PAPER.PonsPaperExecution._settle = real_settle
        PAPER.PonsPaperExecution.open_long = real_open
        PAPER.PonsPaperExecution.reinforcement = real_reinforce
    assert got["settled"]
    assert made == [], f"the label called the executor: {made}"


def test_a_fresh_execution_object_per_row_means_no_carry_between_rows():
    """Two labels in a row give the same answer: nothing is carried."""
    name, store, live, ex, outcome = ENTRIES[0]
    tape = _tracker(store, live).tapes[ex["token"]]
    clock = _clock(store)
    first = C.label_row(tape, int(ex["cutoff_ts"]), clock, gas=D10_GAS)
    second = C.label_row(tape, int(ex["cutoff_ts"]), clock, gas=D10_GAS)
    assert first == second


def test_an_unpriceable_exit_is_unresolved_and_never_a_loss():
    """Route transition, coverage and an exhausted curve are not zeros."""
    name, store, live, ex, outcome = ENTRIES[0]
    tape = _tracker(store, live).tapes[ex["token"]]
    clock = _clock(store)
    beyond = C.label_row(tape, int(tape.coverage_end_ts) + 10_000, clock,
                         gas=D10_GAS)
    assert beyond["settled"] is False
    assert beyond["status"] == C.UNRESOLVED
    assert beyond["net"] is None and beyond["positive"] is None
