"""The loop under admission v2: held positions survive, empty rounds are named,
and a D10 configuration still takes the D10 path.

Owner bullet 8, plus the round statuses `NO_ELIGIBLE_CANDIDATES` and
`DATA_LAG`. The loop, the paper execution and the curve quote are real; the
brain, the readout and the journal are the D10 stubs
(``tests.d10.test_loop``), so what is tested is the mechanics and not the brain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flytrade import records as REC
from flytrade.market import Universe
from flytrade.pons import loop as LOOP
from flytrade.pons import paper as PAPER
from flytrade.pons.admission import AdmissionPolicy
from flytrade.pons.admission_v2 import (DATA_LAG, INACTIVE,
                                        NO_ELIGIBLE_CANDIDATES,
                                        AdmissionPolicyV2)
from flytrade.pons.context_v2 import PONS_FEATURES_V2, context_v2
from tests.d10.test_loop import (FakeDriver, _FakeCredit, _FakeJournal,
                                 _FakeMB, _FakePolicy, _FakeRunner)
from tests.d11 import fixtures as F

ROOT = Path(__file__).resolve().parents[2]
V2_SCALES = json.loads(
    (ROOT / "experiments" / "d11" / "config.json").read_text())["features"]["scales"]


class FakeEncoderV2:
    """The real v2 feature path, a stub olfactory encoder. Deterministic."""

    version = "pons_encoder_v2"

    def __init__(self):
        self.features = PONS_FEATURES_V2
        self.scales = dict(V2_SCALES)


def build(tmp_path, *, tapes, admission=None, context_fn=context_v2,
          encoder=None, branch="v2"):
    driver = FakeDriver(tapes=tapes)
    mb = _FakeMB()
    loop = LOOP.PonsLoop(
        driver=driver, run=_FakeRunner(), mb=mb, credit=_FakeCredit(mb),
        journal=_FakeJournal(tmp_path / branch),
        encoder=encoder or FakeEncoderV2(),
        admission=admission or AdmissionPolicyV2(),
        execution=PAPER.PonsPaperExecution(), policy=_FakePolicy(),
        universe=Universe(), mode=LOOP.MODE_REPLAY, learning=LOOP.LEARN,
        branch=branch, run_id="scripted", context_fn=context_fn,
        log=lambda *a, **k: None)
    loop.tapes = dict(tapes)
    loop.by_curve = {t.curve: t for t in tapes.values()}
    for token in tapes:
        loop.universe.register(token)
    return loop


def busy_tape(**kw):
    """Trades every 30 s for the whole window, so it is always admissible."""
    return F.traded_at(tuple(range(20, 1_300, 25)), **kw)


# ------------------------- bullet 8: a held position outlives its admission
def test_a_held_position_is_observed_and_settled_after_its_token_goes_quiet(
        tmp_path):
    """The token stops trading right after the entry and is never readmitted."""
    tape = F.traded_at((20, 40, 60, 80, 100, 120, 140))
    loop = build(tmp_path, tapes={tape.token: tape})
    loop.run_branch()

    assert len(loop.x.outcomes) == 1, "the episode settled at its horizon"
    assert loop.marks > 0, "it was marked on every tick while held"
    assert len(loop.journal.settled) == 1

    # and at the cutoff of the settlement the token is not admissible at all
    entry = loop.episodes[0]
    pol = AdmissionPolicyV2()
    at_exit = int(entry["exit_ts"])
    verdict = pol.consider(tape, context_v2(tape, at_exit), stable_id=0,
                           cutoff=at_exit)
    assert not verdict.admitted and INACTIVE in verdict.reasons


def test_admission_gates_entries_and_never_exits(tmp_path):
    tape = F.traded_at((20, 40, 60, 80, 100, 120, 140))
    loop = build(tmp_path, tapes={tape.token: tape})
    loop.run_branch()
    closes = [o.close_reason.value for o in loop.x.outcomes]
    assert closes and all(c == "POLICY_CLOSE_FIXED_HOLD" for c in closes)
    assert loop.x.account.position is None, "nothing was left open"


# --------------------------------------------- the two round statuses
def test_a_round_with_nothing_eligible_is_recorded_as_NO_ELIGIBLE_CANDIDATES(
        tmp_path):
    tape = F.tape()            # launched, never traded: INACTIVE at every tick
    loop = build(tmp_path, tapes={tape.token: tape})
    loop.run_branch()
    assert loop.tally.per_round[NO_ELIGIBLE_CANDIDATES] > 0
    assert loop.tally.per_round.get("NO_USABLE_CANDIDATE", 0) == 0
    assert loop.x.outcomes == [], "no entry was forced"
    lines = [json.loads(l) for l in
             loop.journal.log.path.read_text().splitlines() if l.strip()]
    aborted = [r for r in lines if r["kind"] == "ROUND_ABORTED"]
    assert aborted, "an empty round leaves a record, not a silence"
    assert NO_ELIGIBLE_CANDIDATES in aborted[0]["reason"]
    assert INACTIVE in aborted[-1]["reason"], "with the per-token reasons"


def test_a_collector_outage_names_the_round_DATA_LAG(tmp_path):
    """A token trading all the way through, and our own data two ticks late."""
    tape = busy_tape()
    policy = AdmissionPolicyV2()
    loop = build(tmp_path, tapes={tape.token: tape}, admission=policy)
    policy.data_as_of = F.FIRST_TS - 1_000    # every cutoff is behind it
    loop.run_branch()
    assert loop.tally.per_round[DATA_LAG] > 10
    assert loop.x.outcomes == [], "nothing was entered on stale data"
    lines = [json.loads(l) for l in
             loop.journal.log.path.read_text().splitlines() if l.strip()]
    lagged = [r for r in lines if r["kind"] == "ROUND_ABORTED"
              and DATA_LAG in r["reason"]]
    assert lagged and "COLLECTOR_LAG" in lagged[0]["reason"]
    assert not any(INACTIVE in r["reason"] for r in lagged), \
        "a collector outage is never reported as every token going inactive"
    # The only rounds named NO_ELIGIBLE_CANDIDATES are the opening ticks at
    # which nothing was tracked at all: an empty tracked set is not an outage.
    assert (loop.tally.per_round[DATA_LAG]
            > loop.tally.per_round.get(NO_ELIGIBLE_CANDIDATES, 0))


def test_a_v1_loop_keeps_the_counter_it_always_kept(tmp_path):
    """A D10 configuration takes the D10 code path, name for name."""
    from tests.d10.test_loop import FakeEncoder
    from tests.d10 import fixtures as FD

    tape = FD.tape()                    # no trades: v1 refuses it as unusable
    loop = build(tmp_path, tapes={tape.token: tape},
                 admission=AdmissionPolicy(), context_fn=None,
                 encoder=FakeEncoder(), branch="v1")
    loop.run_branch()
    assert loop.tally.per_round["NO_USABLE_CANDIDATE"] > 0
    assert loop.tally.per_round.get(NO_ELIGIBLE_CANDIDATES, 0) == 0
    assert loop.tally.per_round.get(DATA_LAG, 0) == 0
    lines = [json.loads(l) for l in
             loop.journal.log.path.read_text().splitlines() if l.strip()]
    assert not [r for r in lines if r["kind"] == "ROUND_ABORTED"], \
        "v1 wrote no round-aborted record for an empty round and still does not"


def test_the_default_context_is_v1(tmp_path):
    """``context_fn=None`` is ``pons_context_v1``, for every wave before D11."""
    from tests.d10.test_loop import FakeEncoder
    from tests.d10 import fixtures as FD

    tape = FD.traded_tape()
    loop = build(tmp_path, tapes={tape.token: tape},
                 admission=AdmissionPolicy(), context_fn=None,
                 encoder=FakeEncoder(), branch="default")
    ctx = loop.context_fn(tape, F.FIRST_TS + 300)
    assert ctx.version == "pons_context_v1"
    assert set(ctx.raw) == set(FakeEncoder().features)


def test_the_v2_loop_presents_v2_contexts(tmp_path):
    tape = busy_tape()
    loop = build(tmp_path, tapes={tape.token: tape})
    ctx = loop.context_fn(tape, F.FIRST_TS + 300)
    assert ctx.version == "pons_context_v2"
    assert set(ctx.raw) == set(PONS_FEATURES_V2)
