"""The loop: one update per settled episode, no cross-token credit, restart.

The dataset is scripted (``tests.d10.fixtures`` plus the tiny synthetic window
built here): every block, timestamp, launch and trade below is invented so a
test can put two tokens and a settled episode into forty ticks. The brain, the
readout, the credit assigner, the journal and the recovery rule are real.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import execution as X
from flytrade import readout as RO
from flytrade import records as REC
from flytrade import runner as R
from flytrade.market import Universe
from flytrade.pons import loop as LOOP
from flytrade.pons import paper as PAPER
from flytrade.pons.admission import AdmissionPolicy
from flytrade.pons.collector import BlockClock, Finality
from flytrade.pons.context import PONS_FEATURES, TokenTape
from tests.d10 import fixtures as F

SCALES = {"age": 600.0, "ret_30s": 0.0051, "ret_2m": 0.11, "ret_5m": 0.36,
          "flow_imb_2m": 1.0, "trade_rate_2m": 6.0, "rv_2m": 0.029,
          "drawdown_5m": 0.51}


class FakeEncoder:
    """The real feature path, a stub olfactory encoder. Deterministic."""

    version = "pons_encoder_v1"

    def __init__(self):
        self.features = PONS_FEATURES
        self.scales = dict(SCALES)


class FakeDriver:
    """A two-token window on the virtual clock. Every number invented."""

    mode = LOOP.MODE_REPLAY
    label = "scripted"

    def __init__(self, *, tapes, span_seconds=1_400):
        self.clock = F.clock(span_seconds + 200)
        self.coverage_end_ts = F.ts_at(F.block_at(span_seconds))
        self.first_ts = F.FIRST_TS
        self.last_ts = self.coverage_end_ts
        self.admission_last_block = F.block_at(span_seconds)
        self.initial_states = {}
        self.events = []
        self.cursor = 0
        self.tapes = tapes
        self.finality = Finality(F.INTERVAL_S, 10, True, 3)
        self.safe_block = F.block_at(span_seconds + 200)
        self.head_block = self.safe_block

    @property
    def block_clock(self):
        return self.clock

    def advance(self, cutoff):
        return []

    def ticks(self, cadence=LOOP.CADENCE_S):
        t = self.first_ts
        while t <= self.last_ts:
            yield int(t)
            t += cadence

    def confirm(self, block_number):
        from flytrade.pons.collector import is_confirmed
        return {"block_number": int(block_number),
                "confirmed": is_confirmed(int(block_number), head=self.head_block,
                                          finality=self.finality,
                                          safe_block=self.safe_block),
                "head": self.head_block, "safe_block": self.safe_block,
                "confirm_depth": self.finality.confirm_depth,
                "source": "scripted"}

    def as_dict(self):
        return {"mode": self.mode, "dataset": self.label, "events": 0,
                "first_ts": self.first_ts, "last_ts": self.last_ts}


def build(tmp_path, *, learning=LOOP.LEARN, restart_after=None, tapes=None,
          branch="learning"):
    """A loop over a stub brain, so the mechanics are tested and not the brain."""
    tapes = tapes or {}
    driver = FakeDriver(tapes=tapes)
    mb = _FakeMB()
    credit = _FakeCredit(mb)
    journal = _FakeJournal(tmp_path / branch)
    execution = PAPER.PonsPaperExecution()
    loop = LOOP.PonsLoop(
        driver=driver, run=_FakeRunner(), mb=mb, credit=credit, journal=journal,
        encoder=FakeEncoder(), admission=AdmissionPolicy(), execution=execution,
        policy=_FakePolicy(), universe=Universe(), mode=LOOP.MODE_REPLAY,
        learning=learning, branch=branch, run_id="scripted",
        restart_after=restart_after, log=lambda *a, **k: None)
    loop.tapes = dict(tapes)
    loop.by_curve = {t.curve: t for t in tapes.values()}
    for token in tapes:
        loop.universe.register(token)
    return loop


# ------------------------------------------------------------------- stubs
class _FakeMB:
    def __init__(self):
        self.gain = np.ones(4, dtype=np.float32)
        self.pos = np.arange(4)
        self.trace = np.zeros(4)
        self.trace_episode = np.full(4, -1)

    def apply(self):
        pass


class _FakeCredit:
    def __init__(self, mb):
        self.mb = mb
        self.open = {}
        self.settled = set()
        self.applied = []

    def open_episode(self, trace):
        return trace

    def settle(self, episode_id, valence, amount=1.0):
        self.applied.append((int(episode_id), int(valence), float(amount)))
        self.settled.add(int(episode_id))
        return R.LearningEvent(episode_id=int(episode_id), valence=int(valence),
                               amount=float(amount), accepted=True, k=8)

    def stats(self):
        return {"accepted": len(self.applied), "settled": sorted(self.settled)}


class _FakeJournal:
    versions = REC.Versions(market="m", encoder="e", runner="r", decoder="d",
                            execution="x", mushroom="mb", graph_sha256="0" * 64)

    def __init__(self, directory):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = REC.EventLog(self.dir / "events.jsonl")
        self.pending_path = self.dir / "pending.npz"
        self.stamp = {}
        self.decisions = {}
        self.frozen_settled = 0
        self.settled = []
        self.frozen = []

    def checkpoint_digest(self):
        return "0" * 64

    def _append(self, kind, payload):
        return self.log.append(kind, {**payload, **self.stamp})

    def record_discovery(self, **f):
        return self._append(REC.EventType.DISCOVERY, f)

    def record_unresolved(self, **f):
        return self._append(REC.EventType.UNRESOLVED, f)

    def record_round(self, rnd, extra=None):
        return self._append(REC.EventType.ROUND, {**(extra or {}), "round": 1})

    def record_round_aborted(self, **f):
        return self._append(REC.EventType.ROUND_ABORTED, f)

    def record_decision(self, rec, extra=None):
        self.decisions[rec.episode_id] = rec
        return self._append(REC.EventType.DECISION,
                            {**(extra or {}), "episode_id": rec.episode_id,
                             "decoded_action": rec.decoded_action})

    def record_partition(self, **f):
        return self._append(REC.EventType.PARTITION, f)

    def open_episode(self, rec, trace, execution):
        return self._append(REC.EventType.EXECUTION,
                            {"episode_id": rec.episode_id, **execution})

    def settle(self, episode_id, outcome, valence, amount, *, extra=None):
        self.settled.append((int(episode_id), int(valence), float(amount)))
        self._append(REC.EventType.OUTCOME, {"episode_id": int(episode_id)})
        event = R.LearningEvent(episode_id=int(episode_id), valence=int(valence),
                                amount=float(amount), accepted=True, k=8)
        self._append(REC.EventType.LEARNING,
                     {"episode_id": int(episode_id), **event.as_dict()})
        return event

    def settle_frozen(self, episode_id, outcome):
        self.frozen.append(int(episode_id))
        self.frozen_settled += 1
        self._append(REC.EventType.OUTCOME,
                     {"episode_id": int(episode_id),
                      "settlement": "SETTLED_FROZEN"})
        return {"episode_id": int(episode_id)}

    def stats(self):
        return {"settled": len(self.settled)}


class _FakeDecision:
    def __init__(self, action):
        self.action = action
        self.status = D.ReadoutStatus.VALID
        self.valence_hz = 1.0

    def as_dict(self):
        return {"action": self.action.value, "status": self.status.value,
                "valence_hz": self.valence_hz}


class _FakeDecoder:
    """The scripted script: BUY until the first entry, then SELL for ever.

    Invented, and labelled as such. It exists so the loop's *mechanics* — one
    update per settled episode, the fixed-hold refusal, the horizon close — can
    be tested without the brain's answer deciding whether the test runs.
    """

    def __init__(self, buy_until: int = 3):
        self.calls = 0
        self.buy_until = int(buy_until)

    def decode(self, presentation):
        self.calls += 1
        return _FakeDecision(D.Action.BUY if self.calls <= self.buy_until
                             else D.Action.SELL)

    def as_dict(self):
        return {"version": "scripted"}


class _FakePresentation:
    silent_replicates = 0

    def as_dict(self):
        return {"rates_hz": {}, "k": 8}


class _FakeCandidate:
    def __init__(self, stable_id, episode_id, symbol, observation):
        self.stable_id = stable_id
        self.episode_id = episode_id
        self.symbol = symbol
        self.seed = 1
        self.k = 8
        self.presentation = _FakePresentation()
        self.batch = None
        self.traces = None
        self.trace = None
        self.observation = observation
        self.stimulus = None


class _FakeRound:
    def __init__(self, candidates, selected):
        self.candidates = tuple(candidates)
        self.selected = selected


class _FakePolicy:
    def __init__(self):
        self.decoder = _FakeDecoder()
        self.k = 8

    def score(self, c):
        return 1.0

    def as_dict(self):
        return {"k": 8, "namespace": "comparison_v1"}


class _FakeRunner:
    def evaluate_round(self, observations, *, round_index, readout, score):
        cands = [_FakeCandidate(int(o.stable_id),
                                R.episode_id_for(round_index, int(o.stable_id)),
                                o.symbol, o)
                 for o in observations]
        return _FakeRound(cands, cands[0] if cands else None)


# ------------------------------------------------------------------- tests
def _two_tapes():
    a = F.traded_tape(token="0x" + "a" * 40, curve="0x" + "1" * 40)
    b = F.traded_tape(token="0x" + "b" * 40, curve="0x" + "2" * 40)
    return {a.token: a, b.token: b}


def test_one_settled_episode_produces_exactly_one_normalised_update(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes())
    out = loop.run_branch()
    assert len(out["episodes"]) == 1
    assert len(loop.journal.settled) == 1
    episode_id, valence, amount = loop.journal.settled[0]
    assert valence in (-1, 1)
    assert 0.0 < amount <= 1.0
    learning = [json.loads(line) for line in
                loop.journal.log.path.read_text().splitlines()
                if '"LEARNING"' in line]
    assert len(learning) == 1


def test_the_update_is_credited_to_the_entry_episode_and_no_other(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes())
    out = loop.run_branch()
    entry = [json.loads(line) for line in
             loop.journal.log.path.read_text().splitlines()
             if '"EXECUTION"' in line][0]
    settled_id = loop.journal.settled[0][0]
    assert settled_id == entry["episode_id"]
    assert out["episodes"][0]["episode_id"] == settled_id


def test_no_cross_token_credit_contamination(tmp_path):
    """The other token in the window never receives the episode's update."""
    tapes = _two_tapes()
    loop = build(tmp_path, tapes=tapes)
    out = loop.run_branch()
    settled_token = out["episodes"][0]["token"]
    other = [t for t in tapes if t != settled_token][0]
    assert len(loop.journal.settled) == 1
    outcomes = [json.loads(line) for line in
                loop.journal.log.path.read_text().splitlines()
                if line.strip() and json.loads(line)["kind"] == "OUTCOME"]
    assert len(outcomes) == 1
    learning = [json.loads(line) for line in
                loop.journal.log.path.read_text().splitlines()
                if line.strip() and json.loads(line)["kind"] == "LEARNING"]
    assert len(learning) == 1
    # the other token's stable id never appears in a settled episode
    assert loop.universe.stable_id(other) != loop.universe.stable_id(settled_token)
    assert all(e["episode_id"] == settled_id
               for e in outcomes + learning
               for settled_id in [loop.journal.settled[0][0]])


def test_a_decoded_sell_while_holding_is_refused_and_sells_nothing(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes())
    out = loop.run_branch()
    assert out["tally"]["after_execution_constraints"]["blocked_by_fixed_hold"] > 0
    assert out["execution"]["rejections"]["FIXED_HOLD"] > 0
    assert out["execution"]["close_reasons"] == {"POLICY_CLOSE_FIXED_HOLD": 1}


def test_the_position_closes_at_the_horizon_and_not_before(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes())
    out = loop.run_branch()
    episode = out["episodes"][0]
    assert episode["seconds_held"] == PAPER.HORIZON_S
    assert episode["close_reason"] == "POLICY_CLOSE_FIXED_HOLD"


def test_a_mark_is_recorded_every_tick_while_holding_and_is_never_a_reward(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes())
    out = loop.run_branch()
    assert out["marks"] >= PAPER.HORIZON_S // LOOP.CADENCE_S - 2
    rounds = [json.loads(line) for line in
              loop.journal.log.path.read_text().splitlines()
              if '"ROUND"' in line]
    marks = [r["mark"] for r in rounds if isinstance(r.get("mark"), dict)]
    assert marks
    assert all(m["is_a_reward"] is False for m in marks if m.get("available"))


def test_frozen_settles_for_accounting_and_applies_nothing(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes(), learning=LOOP.FROZEN,
                 branch="frozen_reference")
    out = loop.run_branch()
    assert len(out["episodes"]) == 1
    assert loop.journal.settled == []
    assert loop.journal.frozen_settled == 1
    assert loop.credit.stats()["accepted"] == 0
    assert out["digest_unchanged"] is True
    assert '"LEARNING"' not in loop.journal.log.path.read_text()


def test_every_d10_record_carries_the_venue_and_the_chain(tmp_path):
    loop = build(tmp_path, tapes=_two_tapes())
    loop.run_branch()
    lines = [json.loads(line) for line in
             loop.journal.log.path.read_text().splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert line["venue"] == "PONS"
        assert line["chain_id"] == 4663
        assert line["mode"] == LOOP.MODE_REPLAY
        assert line["learning"] == LOOP.LEARN


def test_a_completed_curve_leaves_the_position_unresolved_and_teaches_nothing(
        tmp_path):
    tapes = _two_tapes()
    loop = build(tmp_path, tapes=tapes)
    # complete both curves shortly after the first entry could have happened
    for tape in tapes.values():
        tape.apply(F.completed_event(tape.curve, at_seconds=200))
    out = loop.run_branch()
    assert out["episodes"] == []
    assert loop.journal.settled == []
    assert '"LEARNING"' not in loop.journal.log.path.read_text()


def test_an_unresolved_position_is_recorded_once_per_reason(tmp_path):
    tapes = {k: v for k, v in list(_two_tapes().items())[:1]}
    tape = list(tapes.values())[0]
    loop = build(tmp_path, tapes=tapes)
    loop._unresolve(1, tape.token, PAPER.ROUTE_TRANSITION, "x", 0)
    loop._unresolve(1, tape.token, PAPER.ROUTE_TRANSITION, "x", 30)
    loop._unresolve(1, tape.token, PAPER.ROUTE_TRANSITION, "x", 60)
    assert len(loop.unresolved) == 1
    records = [line for line in loop.journal.log.path.read_text().splitlines()
               if '"UNRESOLVED"' in line]
    assert len(records) == 1
    assert json.loads(records[0])["is_a_loss"] is False


def test_the_mode_and_the_learning_mode_are_validated(tmp_path):
    with pytest.raises(ValueError):
        build(tmp_path, learning="MAYBE")
    with pytest.raises(ValueError):
        LOOP.PonsLoop(driver=None, run=None, mb=None, credit=None, journal=None,
                      encoder=None, admission=None, execution=None, policy=None,
                      universe=None, mode="NOPE", learning=LOOP.LEARN,
                      branch="b", run_id="r")


def test_the_live_driver_implements_the_whole_driver_contract():
    """Dispatch 3 completed the stub this test used to pin.

    It asserted that ``LIVE_PAPER`` raised ``NotImplementedError`` rather than
    quietly doing nothing. The driver is implemented now, so what keeps that
    meaning is the contract itself: every attribute :class:`PonsLoop` reads off
    a driver is present, the mode is the live one, and the stop limits are the
    ones addendum 15 declares. The behaviour behind them is exercised against a
    scripted endpoint in ``tests/d10/test_live.py``.
    """
    driver = LOOP.LiveDriver(collector=None, finality=Finality(0.1, 1, True, 2))
    for name in ("advance", "ticks", "confirm", "block_clock", "health",
                 "as_dict"):
        assert hasattr(type(driver), name), name
    for name in ("initial_states", "admission_last_block", "coverage_end_ts",
                 "last_ts", "label", "mode"):
        assert hasattr(driver, name), name
    assert driver.mode == LOOP.MODE_LIVE
    assert driver.limits.max_seconds == LOOP.LIVE_MAX_SECONDS == 3_600
    assert driver.limits.max_requests == LOOP.LIVE_MAX_REQUESTS == 3_000
    assert driver.advance(0) == []        # nothing polled, nothing handed over
