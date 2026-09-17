"""
Canonical event → displayed state. Amendment D9(a) §9, addendum 3.

Every distinction amendment §4 insists on is a named branch in
``observer/projection.py``, and this file is where each one is held to the
record: WAIT against NO_RESPONSE against a saturated readout; a SELL signal
against an executed sale; a neural closure against a policy closure; a FROZEN
settlement against a learning update; an outcome whose update was refused;
telemetry that was never recorded. The fixtures carry
``dataset_label = SYNTHETIC_FIXTURE`` in every event, so nothing here can be
mistaken for a historical result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "observer"))

import projection as P                                # noqa: E402

from . import fixtures as F                           # noqa: E402


@pytest.fixture(scope="module")
def learned():
    return P.project(F.learning_branch().events, horizon_minutes=5,
                     horizon_source="fixture")


@pytest.fixture(scope="module")
def frozen():
    return P.project(F.frozen_branch().events, horizon_minutes=5,
                     horizon_source="fixture")


def by_kind(out, kind):
    return [f for f in out["frames"] if f["kind"] == kind]


def ev(out, seq):
    return out["frames"][seq]["ev"]


# ------------------------------------------------- the fixtures are labelled

def test_every_fixture_event_says_it_is_synthetic():
    for log in (F.learning_branch(), F.frozen_branch()):
        assert log.events
        for e in log.events:
            assert e["dataset_label"] == "SYNTHETIC_FIXTURE"


# ------------------------------------------------------- one frame per event

def test_one_frame_per_event_in_file_order_with_seq_as_the_tie_break(learned):
    src = F.learning_branch().events
    assert len(learned["frames"]) == len(src)
    for i, (f, e) in enumerate(zip(learned["frames"], src)):
        assert f["seq"] == i
        assert f["kind"] == e["kind"]
    seqs = [f["seq"] for f in learned["frames"]]
    assert seqs == sorted(seqs)


def test_two_events_sharing_a_timestamp_keep_their_file_order(learned):
    """§5: sequence, not only the clock, orders the stream."""
    ts = {}
    for f in learned["frames"]:
        if f.get("ts") is not None:
            ts.setdefault(f["ts"], []).append(f["seq"])
    shared = [v for v in ts.values() if len(v) > 1]
    assert shared, "the fixture must contain same-timestamp events"
    for group in shared:
        assert group == sorted(group)


# ------------------------------------------------------- §4: the four states

def test_wait_is_not_no_response_and_neither_is_an_invalid_readout(learned):
    d = {f["ev"]["episode_id"]: f["ev"] for f in by_kind(learned, "DECISION")}
    assert d[1000]["action"] == "WAIT" and d[1000]["status"] == "VALID"
    assert d[2000]["action"] == "NO_RESPONSE"
    assert d[2000]["status"] == "NO_RESPONSE"
    assert d[3000]["status"] == "INVALID_STATE"
    # the saturated readout is a recorded condition, not a decision
    assert d[3000]["action"] == "NO_RESPONSE"
    assert d[3000]["kc_fraction"] > 0.25
    last = learned["frames"][-1]["at"]["c"]
    c = dict(zip(P.COUNTERS, last))
    assert c["wait"] == 2 and c["no_response"] == 1 and c["invalid_state"] == 1


def test_a_sell_signal_with_no_position_is_never_an_executed_sale(learned):
    sell = next(f for f in by_kind(learned, "DECISION")
                if f["ev"]["action"] == "SELL")
    at = learned["frames"][sell["seq"]]["at"]
    assert at.get("position") is None, "no position was open at that signal"
    # and no EXECUTION event exists for that episode at all
    assert all(f["ev"].get("episode_id") != sell["ev"]["episode_id"]
               for f in by_kind(learned, "EXECUTION"))
    c = dict(zip(P.COUNTERS, learned["frames"][-1]["at"]["c"]))
    assert c["sell"] == 1 and c["executions"] == 3


def test_an_execution_policy_rejection_is_its_own_state(learned):
    rej = next(f for f in by_kind(learned, "DECISION")
               if f["ev"]["status"] == "POLICY_REJECT")
    assert rej["ev"]["action"] == "BUY", "the decoder did decide; policy said no"
    assert learned["frames"][rej["seq"]]["at"].get("position") is None
    c = dict(zip(P.COUNTERS, learned["frames"][-1]["at"]["c"]))
    assert c["policy_reject"] == 1
    # a rejected BUY is not counted as a decoded BUY
    assert c["buy"] == 3


def test_a_round_that_produced_no_decision_is_counted_as_one(learned):
    c = dict(zip(P.COUNTERS, learned["frames"][-1]["at"]["c"]))
    assert c["rounds"] == 10 and c["decisions"] == 9
    assert c["rounds_no_decision"] == 1
    first = next(f for f in by_kind(learned, "ROUND"))
    assert first["ev"]["observation_status"] == "WARMUP"


# --------------------------------------------------- §4: closure and memory

def test_a_neural_closure_and_a_policy_closure_stay_different_events(learned):
    outs = {f["ev"]["episode_id"]: f["ev"] for f in by_kind(learned, "OUTCOME")}
    assert outs[6000]["close_reason"] == "NEURAL_SELL"
    assert outs[7000]["close_reason"] == "POLICY_CLOSE"
    c = dict(zip(P.COUNTERS, learned["frames"][-1]["at"]["c"]))
    assert c["neural_sell"] == 2 and c["policy_close"] == 1


def test_the_learning_update_of_a_loss_is_the_recorded_event_not_the_sign(
        learned):
    out = next(f for f in by_kind(learned, "OUTCOME")
               if f["ev"]["episode_id"] == 6000)
    assert out["ev"]["net_pnl"] < 0
    # at the outcome itself there is no learning event yet
    assert learned["frames"][out["seq"]]["at"].get("learning") is None
    lrn = next(f for f in by_kind(learned, "LEARNING")
               if f["ev"]["episode_id"] == 6000)
    at = learned["frames"][lrn["seq"]]["at"]
    assert at["learning"] == lrn["seq"] and at["outcome"] == out["seq"]
    assert lrn["ev"]["valence"] == -1 and lrn["ev"]["accepted"] is True
    assert lrn["ev"]["synapses_depressed"] > 0


def test_a_refused_learning_update_shows_its_reason_and_no_change(learned):
    lrn = next(f for f in by_kind(learned, "LEARNING")
               if f["ev"]["episode_id"] == 8000)
    assert lrn["ev"]["accepted"] is False
    assert lrn["ev"]["reason"] == "no eligible synapses"
    assert lrn["ev"]["synapses_depressed"] == 0
    assert "depressed_per_replicate" not in lrn["ev"]


def test_a_frozen_outcome_never_acquires_a_learning_event(frozen):
    assert by_kind(frozen, "LEARNING") == []
    outs = by_kind(frozen, "OUTCOME")
    assert len(outs) == 2
    assert {o["ev"]["settlement"] for o in outs} == {"SETTLED_FROZEN"}
    # one of them is positive: "positive result — learning frozen" is a state
    assert any(o["ev"]["net_pnl"] > 0 for o in outs)
    assert any(o["ev"]["net_pnl"] < 0 for o in outs)
    for o in outs:
        at = frozen["frames"][o["seq"]]["at"]
        assert at.get("learning") is None
        assert at["settlement"] == "SETTLED_FROZEN"
    for f in frozen["frames"]:
        assert f["at"].get("learning") is None
    c = dict(zip(P.COUNTERS, frozen["frames"][-1]["at"]["c"]))
    assert c["settled_frozen"] == 2 and c["learning"] == 0


def test_the_frozen_marker_comes_from_the_settlement_not_the_branch(frozen):
    """Addendum 9: ``settle_frozen`` writes the marker; names prove nothing."""
    raw = F.frozen_branch().events
    for e in raw:
        if e["kind"] == "OUTCOME":
            assert e["settlement"] == "SETTLED_FROZEN"
    # the branch name is carried by the partition, and is not the source
    table = frozen["meta"]["partition_table"]
    assert table[0]["branch"] == "frozen_trained"
    assert table[0]["learning"] is False


# ----------------------------------------------------- §4: missing telemetry

def test_telemetry_that_was_not_recorded_is_absent_not_zero(learned):
    d = next(f for f in by_kind(learned, "DECISION")
             if f["ev"]["episode_id"] == 9000)
    for absent in ("features", "glomeruli", "reps", "rep_scores", "kc_active",
                   "kc_fraction", "close", "pop"):
        assert absent not in d["ev"], absent
    # what *was* recorded is still there
    assert d["ev"]["action"] == "WAIT" and d["ev"]["valence_hz"] == 0.2
    full = next(f for f in by_kind(learned, "DECISION")
                if f["ev"]["episode_id"] == 1000)
    assert len(full["ev"]["features"]) == 5
    assert len(full["ev"]["glomeruli"]) == len(learned["meta"]["channels"])


def test_the_replicate_marks_are_the_recorded_statuses_of_k_equals_eight(
        learned):
    d = next(f for f in by_kind(learned, "DECISION")
             if f["ev"]["episode_id"] == 1000)
    assert d["ev"]["k"] == 8
    assert len(d["ev"]["reps"]) == 8 and len(d["ev"]["rep_scores"]) == 8
    assert set(d["ev"]["reps"]) <= set(P.LETTER_STATUS)
    assert "".join(P.STATUS_LETTER[s] for s in
                   ["VALID"] * 7 + ["NO_RESPONSE"]) == d["ev"]["reps"]
    silent = next(f for f in by_kind(learned, "DECISION")
                  if f["ev"]["episode_id"] == 2000)
    assert silent["ev"]["reps"] == "N" * 8


# ------------------------------------------------------------ §5: no leakage

def test_no_frame_carries_anything_from_a_later_event(learned):
    """The state at N is exactly the projection of events 0..N."""
    src = F.learning_branch().events
    for n in range(len(src)):
        prefix = P.project(src[:n + 1], horizon_minutes=5,
                           horizon_source="fixture")
        assert prefix["frames"][n]["at"] == learned["frames"][n]["at"]
        assert prefix["frames"][n]["ev"] == learned["frames"][n]["ev"]


def test_a_result_is_invisible_before_its_outcome_event(learned):
    out = next(f for f in by_kind(learned, "OUTCOME"))
    for f in learned["frames"][:out["seq"]]:
        assert f["at"].get("outcome") is None
        assert f["at"].get("settlement") is None
    assert learned["frames"][out["seq"]]["at"]["outcome"] == out["seq"]


def test_the_previous_episodes_learning_never_stands_beside_a_new_result(
        learned):
    outs = by_kind(learned, "OUTCOME")
    assert len(outs) >= 2
    for o in outs:
        assert learned["frames"][o["seq"]]["at"].get("learning") is None


def test_the_counters_never_decrease_and_end_at_the_totals(learned):
    prev = [0] * len(P.COUNTERS)
    for f in learned["frames"]:
        cur = f["at"]["c"]
        assert len(cur) == len(P.COUNTERS)
        assert all(b >= a for a, b in zip(prev, cur))
        prev = cur
    c = dict(zip(P.COUNTERS, prev))
    assert c["outcomes"] == 3 and c["learning"] == 3 and c["executions"] == 3


# ------------------------------------------- seek, replay, and the reconnect

def test_seeking_backwards_is_an_index_and_changes_nothing(learned):
    """§6: replaying reconstructs the same as-of state, once."""
    order = [0, 5, 12, 3, 20, 1, len(learned["frames"]) - 1, 12, 3]
    seen = {}
    for i in order:
        f = learned["frames"][i]
        if i in seen:
            assert seen[i] == json.dumps(f, sort_keys=True)
        seen[i] = json.dumps(f, sort_keys=True)


def test_projecting_the_same_log_twice_gives_byte_identical_frames():
    a = P.project(F.learning_branch().events, horizon_minutes=5)
    b = P.project(F.learning_branch().events, horizon_minutes=5)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_a_reload_cannot_double_count_money_or_learning(learned):
    """A reconnect re-reads frames; nothing is accumulated by the reader."""
    again = P.project(F.learning_branch().events, horizon_minutes=5,
                      horizon_source="fixture")
    assert again["frames"][-1]["at"]["c"] == learned["frames"][-1]["at"]["c"]
    totals = [f["ev"]["cumulative_realized_pnl"]
              for f in by_kind(learned, "OUTCOME")]
    assert totals == [f["ev"]["cumulative_realized_pnl"]
                      for f in by_kind(again, "OUTCOME")]


# ------------------------------------------------------- position and horizon

def test_the_open_position_points_at_its_own_execution_event(learned):
    ex = next(f for f in by_kind(learned, "EXECUTION"))
    out = next(f for f in by_kind(learned, "OUTCOME"))
    for f in learned["frames"][ex["seq"]:out["seq"]]:
        assert f["at"]["position"] == ex["seq"]
    assert learned["frames"][out["seq"]].get("at").get("position") is None


def test_the_horizon_countdown_is_a_maximum_and_never_goes_negative(learned):
    ex = next(f for f in by_kind(learned, "EXECUTION"))
    out = next(f for f in by_kind(learned, "OUTCOME"))
    lefts = [learned["frames"][i]["at"].get("horizon_left")
             for i in range(ex["seq"], out["seq"])]
    assert lefts[0] == 5
    assert all(x is not None and 0 <= x <= 5 for x in lefts)
    assert learned["meta"]["horizon_label"] == \
        "remaining maximum policy horizon"


def test_without_a_recorded_horizon_no_countdown_is_invented():
    out = P.project(F.learning_branch().events)
    assert out["meta"]["horizon_minutes"] is None
    assert out["meta"]["horizon_source"] == "unavailable"
    assert all("horizon_left" not in f["at"] for f in out["frames"])
    # the position and its elapsed minutes are still shown: those are recorded
    assert any(f["at"].get("held") is not None for f in out["frames"])


def test_the_horizon_is_read_from_the_run_summary_or_reported_unavailable():
    assert P.horizon_of(F.summary()) == (5, "summary.selected_horizon_minutes")
    cfg = {"config": {"execution": {"horizon_minutes": 8}}}
    assert P.horizon_of(cfg) == (8, "summary.config.execution.horizon_minutes")
    assert P.horizon_of({}) == (None, "unavailable")
    assert P.horizon_of(None) == (None, "unavailable")


# ------------------------------------------------------------- the accounting

def test_every_money_field_is_copied_from_the_outcome_event(learned):
    src = {e["episode_id"]: e for e in F.learning_branch().events
           if e["kind"] == "OUTCOME"}
    for f in by_kind(learned, "OUTCOME"):
        raw = src[f["ev"]["episode_id"]]
        for k in ("net_pnl", "gross_pnl", "gross_reference_pnl", "fees",
                  "slippage", "notional", "cumulative_realized_pnl",
                  "return_on_notional"):
            assert f["ev"][k] == raw[k], k
        assert f["ev"]["account"] == raw["account"]


def test_an_outcome_without_an_account_block_reports_it_absent():
    log = F.Log()
    F.partition(log, "LEARNING", "start", branch="learned", learning=True)
    F.round_(log, i=0, ts=F.T0)
    F.decision(log, episode_id=1000, ts=F.T0, action="BUY", status="VALID",
               valence=2.0, branch="learned", partition_name="LEARNING")
    F.execution(log, episode_id=1000, ts=F.T0 + 60)
    F.outcome(log, episode_id=1000, ts=F.T0 + 120, net=-1.0, account=False)
    out = P.project(log.events)
    o = next(f for f in out["frames"] if f["kind"] == "OUTCOME")
    assert "account" not in o["ev"]
    assert o["ev"]["net_pnl"] == -1.0


def test_the_projection_writes_nothing_and_opens_no_checkpoint():
    """One read-only ``open``, of the event log, and no import of flytrade."""
    src = (ROOT / "observer" / "projection.py").read_text()
    code = [ln for ln in src.splitlines()
            if ln.strip() and not ln.lstrip().startswith(("#", "*", '"""'))]
    assert src.count("open(") == 1
    assert 'with open(path, encoding="utf-8") as fh:' in src
    for forbidden in ("import flytrade", "from flytrade", ".write(",
                      "savez", '"w"', "'w'", "mkdir", "unlink"):
        assert not any(forbidden in ln for ln in code), forbidden


# ------------------------------------------------------------------ the meta

def test_the_meta_declares_the_vocabulary_the_page_renders(learned):
    m = learned["meta"]
    assert m["contract"] == P.CONTRACT
    assert m["features"] == list(P.FEATURES)
    assert m["channels"] == sorted(F.GLOM)
    assert m["counters"] == list(P.COUNTERS)
    assert m["replicate_legend"] == {"V": "VALID", "N": "NO_RESPONSE",
                                     "I": "INVALID_STATE",
                                     "P": "POLICY_REJECT"}
    assert set(m["kind_vocabulary"]) == set(P.KINDS)
    assert m["dataset_label"] == "SYNTHETIC_FIXTURE"


def test_the_jump_index_points_at_real_frames(learned):
    idx = learned["meta"]["index"]
    for key, kind in (("decisions", "DECISION"), ("executions", "EXECUTION"),
                      ("outcomes", "OUTCOME"), ("learning", "LEARNING")):
        assert idx[key] == [f["seq"] for f in by_kind(learned, kind)]
        for s in idx[key]:
            assert learned["frames"][s]["kind"] == kind


def test_the_partition_spans_are_seq_ranges(learned):
    spans = {s["partition"]: s for s in learned["meta"]["partitions"]}
    assert set(spans) == {"LEARNING"}
    s = spans["LEARNING"]
    assert learned["frames"][s["start"]]["kind"] == "PARTITION"
    assert learned["frames"][s["end"]]["kind"] == "PARTITION"
    assert s["start"] < s["end"]


def test_provenance_is_run_level_and_never_an_as_of_value():
    pv = P.provenance(F.summary())
    assert pv["run_id"] == "synthetic-001"
    assert pv["encoder"] == "synthetic-encoder"
    assert pv["decoder"] == "synthetic-decoder"
    assert pv["k"] == 8
    assert pv["selected_horizon_minutes"] == 5
    assert P.provenance(None)["run_id"] is None


def test_a_torn_last_line_is_a_state_not_a_crash(tmp_path):
    log = F.learning_branch()
    p = log.write(tmp_path / "events.jsonl")
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"kind": "DECISION", "episode')
    out = P.load(p, summary=F.summary())
    assert out["frames"][-1]["kind"] == "TORN"
    assert len(out["frames"]) == len(log.events) + 1


# ------------------------------------------- the one test on the real record
# Addendum 12: at most one test asserts on the real ``d7-001/learned`` counts,
# and it is skipped with a reason when that gitignored directory is absent.

D7_LEARNED = (ROOT / "experiments" / "d7" / "runs" / "d7-001" / "learned"
              / "events.jsonl")


@pytest.mark.skipif(not D7_LEARNED.exists(),
                    reason="experiments/d7/runs is gitignored and absent here")
def test_the_default_run_projects_to_the_counts_the_record_states():
    """3,899 rounds, 3,699 decisions, 42 trades, 42 learning events."""
    summary = json.loads((ROOT / "experiments" / "d7"
                          / "learning_summary.json").read_text())
    out = P.load(D7_LEARNED, summary=summary)
    assert len(out["frames"]) == 7786
    c = dict(zip(P.COUNTERS, out["frames"][-1]["at"]["c"]))
    assert c["rounds"] == 3899 and c["decisions"] == 3699
    assert c["executions"] == 42 and c["outcomes"] == 42
    assert c["learning"] == 42 and c["neural_sell"] == 42
    assert c["warmup"] == 13
    # a fly that mostly waits, is sometimes unreadable, and traded 42 times
    assert c["sell"] == 2806 and c["wait"] == 756 and c["buy"] == 71
    assert c["no_response"] == 54 and c["policy_reject"] == 12
    assert c["settled_frozen"] == 0 and c["policy_close"] == 0
    assert out["meta"]["dataset_label"] == "HISTORICAL_MARKET"
    assert out["meta"]["horizon_minutes"] == 90
    # addendum 5: the stream stays inside its payload budget
    size = len(json.dumps(out, separators=(",", ":")).encode())
    assert size <= 5_000_000, f"{size} bytes"
