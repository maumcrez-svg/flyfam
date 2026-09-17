"""
D9(b) §6 — the fixed-hold exit policy, proved on the real loop.

Every test here calls ``experiments/historical/run.py::run_branch``, the
function the flag lives in, with the real execution policy, the real journal,
the real credit assigner and a real mushroom body over the built connectome.
Only the *simulator* is scripted (``tests/d9b/scripted.py`` says why), so that
a test can place a SELL at a chosen minute while a position is open.

The seven properties amendment §6 names, one section each, plus the flag's own
refusal of an unknown value.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from flytrade import execution as X
from flytrade import historical as H
from flytrade import horizon as HZ
from flytrade import records as REC

from .conftest import DAYS, requires_real_graph
from . import scripted as SC

NEURAL_OR_HORIZON = "neural_or_horizon"
FIXED_HOLD = "fixed_hold"
#: the fixture sessions are 120 minutes long, so the loop tests hold for 8
#: market minutes. H is a number the policy carries, not a branch in it; the
#: wave's own H = 90 is exercised against the clock rule in its own section.
Hf = 8


# ------------------------------------------------------------- helpers

def usable(series, day):
    return [m for m in range(120)
            if series.observe(day, m, stable_id=0).status.usable]


def events(journal, kind=None):
    evs = journal.log.read()
    return [e for e in evs if kind is None or e.get("kind") == kind]


def outcomes(journal):
    return events(journal, "OUTCOME")


#: the two fields of an event that are not the experiment: the wall clock the
#: log stamps on every line, and the absolute path of the run store.
VOLATILE = ("t", "path")


def comparable(journal):
    return [{k: v for k, v in e.items() if k not in VOLATILE}
            for e in journal.log.read()]


def run(mb, series, tmp_path, script, *, policy, days=(DAYS[2],),
        horizon=Hf, learning=True, name="learned", restart_after=None,
        start_gain=None):
    return SC.run_scripted(
        mb=mb, series=series, symbol="A", script=script,
        store=tmp_path / f"store-{name}-{policy}", horizon=horizon, days=days,
        exit_policy=policy, learning=learning, name=name,
        restart_after=restart_after, start_gain=start_gain)


@pytest.fixture
def mb(brain):
    """The real mushroom body, with clean weights around each test."""
    _, body, _, _ = brain
    body.gain[:] = 1.0
    body.trace[:] = 0.0
    body.trace_episode[:] = -1
    body.events = {"reward": 0, "punish": 0, "rejected_episode": 0}
    body.apply()
    yield body
    body.gain[:] = 1.0
    body.trace[:] = 0.0
    body.trace_episode[:] = -1
    body.apply()


# ------------------------------- §6.1  an early SELL cannot close ------

@requires_real_graph
def test_an_early_neural_sell_cannot_close_a_fixed_hold_position(
        mb, series_a, tmp_path):
    day = DAYS[2]
    u = usable(series_a, day)
    script = {u[0]: "BUY", u[1]: "SELL", u[2]: "SELL"}

    out_d, j_d, _, _, _ = run(mb, series_a, tmp_path, script,
                              policy=NEURAL_OR_HORIZON, name="dflt")
    out_f, j_f, acc_f, _, _ = run(mb, series_a, tmp_path, script,
                                  policy=FIXED_HOLD, name="fixed")

    # the default: the first SELL closed the position, as D5/D6/D7 did
    od = outcomes(j_d)
    assert [e["close_reason"] for e in od] == [X.CloseReason.NEURAL_SELL.value]
    assert od[0]["exit"]["bar_index"] == u[1] + 1

    # fixed_hold: the SELLs closed nothing and the horizon did
    of = outcomes(j_f)
    assert [e["close_reason"] for e in of] == \
        [X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value]
    assert X.CloseReason.NEURAL_SELL.value not in \
        [e["close_reason"] for e in of]
    entry_minute = of[0]["entry"]["bar_index"]
    assert of[0]["exit"]["bar_index"] == entry_minute + Hf
    assert of[0]["market_minutes_held"] == Hf
    # and it was held straight through both SELL minutes
    assert entry_minute <= u[1] < of[0]["exit"]["bar_index"]
    assert entry_minute <= u[2] < of[0]["exit"]["bar_index"]

    tally = out_f["partitions"]["LEARNING"]["tally"][
        "after_execution_constraints"]
    assert tally["blocked_by_fixed_hold"] == 2
    assert X.CloseReason.NEURAL_SELL.value not in tally
    assert tally[X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value] == 1
    assert out_f["exit_policy"] == FIXED_HOLD
    assert out_d["exit_policy"] == NEURAL_OR_HORIZON


@requires_real_graph
def test_a_blocked_sell_is_a_rejection_in_the_log_with_its_own_reason(
        mb, series_a, tmp_path):
    day = DAYS[2]
    u = usable(series_a, day)
    script = {u[0]: "BUY", u[1]: "SELL"}
    _, journal, accounts, _, _ = run(mb, series_a, tmp_path, script,
                                     policy=FIXED_HOLD)

    decisions = events(journal, "DECISION")
    blocked = [e for e in decisions
               if (e.get("rejection") or {}).get("reason")
               == X.RejectReason.FIXED_HOLD.value]
    assert len(blocked) == 1
    b = blocked[0]
    assert b["decoded_action"] == "SELL"           # the decoder did decide
    assert b["readout_status"] == "POLICY_REJECT"  # the policy refused
    assert b["rejection"]["action"] == "SELL"
    assert b["bar_index"] == u[1]
    # no execution and no outcome was written at that minute
    assert not [e for e in events(journal, "EXECUTION")
                if e["bar_index"] == u[1] + 1]
    assert all(e["exit"]["bar_index"] != u[1] + 1 for e in outcomes(journal))
    # the rejection is on the account's own rejection list, by reason
    pol = accounts["LEARNING"]
    assert pol.stats()["rejections"][X.RejectReason.FIXED_HOLD.value] == 1
    # a blocked signal is not a trade and not an execution
    assert pol.account.trades == 1


# --------------------------- §6.2  entry stays the decoder's ----------

@requires_real_graph
def test_no_entry_is_forced_when_the_decoder_never_says_buy(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {u[1]: "SELL", u[2]: "WAIT", u[3]: "NO_RESPONSE"}
    out, journal, accounts, credit, _ = run(mb, series_a, tmp_path, script,
                                            policy=FIXED_HOLD)
    assert out["execution"]["trades"] == 0
    assert events(journal, "EXECUTION") == []
    assert events(journal, "OUTCOME") == []
    assert events(journal, "LEARNING") == []
    assert credit.accepted == 0
    assert accounts["LEARNING"].account.position is None
    # the rounds still happened and the decisions were still recorded
    assert len(events(journal, "DECISION")) == len(u)


@requires_real_graph
def test_a_second_buy_while_holding_neither_adds_nor_reverses(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {u[0]: "BUY", u[1]: "BUY", u[2]: "BUY"}
    out, journal, accounts, _, _ = run(mb, series_a, tmp_path, script,
                                       policy=FIXED_HOLD)
    ex = events(journal, "EXECUTION")
    # one entry per episode; the repeats were HOLD:BUY, not new positions
    firsts = [e for e in ex if e["side"] == "BUY"]
    assert len(firsts) == len({e["episode_id"] for e in firsts})
    tally = out["partitions"]["LEARNING"]["tally"][
        "after_execution_constraints"]
    assert tally.get("HOLD:BUY", 0) == 2
    assert tally.get("POLICY_REJECT:POSITION_OPEN", 0) == 0
    for o in outcomes(journal):
        assert o["exit"]["side"] == "SELL"
        assert o["notional"] == 1000.0


# ------------- §6.3  the default flag is the pre-flag behaviour --------

@requires_real_graph
def test_the_default_reproduces_the_pre_flag_loop_event_for_event(
        mb, series_a, tmp_path):
    """Omitting the argument and passing the default must be one behaviour."""
    u = usable(series_a, DAYS[2])
    script = {u[0]: "BUY", u[2]: "SELL", u[5]: "BUY", u[20]: "SELL",
              u[30]: "BUY"}

    out_omitted, j_omitted, _, _, _ = SC.run_scripted(
        mb=mb, series=series_a, symbol="A", script=script,
        store=tmp_path / "omitted", horizon=Hf, days=(DAYS[2],),
        exit_policy=None, name="learned")
    out_default, j_default, _, _, _ = SC.run_scripted(
        mb=mb, series=series_a, symbol="A", script=script,
        store=tmp_path / "default", horizon=Hf, days=(DAYS[2],),
        exit_policy=NEURAL_OR_HORIZON, name="learned")

    a = comparable(j_omitted)
    b = comparable(j_default)
    assert len(a) == len(b) > 0
    assert a == b                                   # event for event
    assert out_omitted["execution"] == out_default["execution"]
    assert out_omitted["partitions"]["LEARNING"]["end_digest"] == \
        out_default["partitions"]["LEARNING"]["end_digest"]

    # and it is the D5/D6/D7 closure sequence: a SELL closes, the horizon
    # closes, and no POLICY_CLOSE_FIXED_HOLD exists anywhere
    reasons = [e["close_reason"] for e in outcomes(j_default)]
    assert X.CloseReason.NEURAL_SELL.value in reasons
    assert X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value not in reasons
    assert all(r in (X.CloseReason.NEURAL_SELL.value,
                     X.CloseReason.POLICY_CLOSE.value) for r in reasons)
    assert "blocked_by_fixed_hold" not in out_default["partitions"][
        "LEARNING"]["tally"]["after_execution_constraints"]


@requires_real_graph
def test_the_default_and_fixed_hold_agree_until_the_first_blocked_sell(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {u[0]: "BUY", u[3]: "SELL"}
    _, j_d, _, _, _ = run(mb, series_a, tmp_path, script,
                          policy=NEURAL_OR_HORIZON)
    _, j_f, _, _, _ = run(mb, series_a, tmp_path, script,
                          policy=FIXED_HOLD)
    a, b = comparable(j_d), comparable(j_f)
    # identical up to the decision that the fixed-hold policy refuses
    same = 0
    while same < min(len(a), len(b)) and a[same] == b[same]:
        same += 1
    assert a[same]["kind"] == b[same]["kind"] == "DECISION"
    assert a[same]["bar_index"] == b[same]["bar_index"] == u[3]
    assert a[same]["readout_status"] == "VALID"
    assert b[same]["readout_status"] == "POLICY_REJECT"


def test_an_unknown_exit_policy_is_refused_before_anything_runs():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "experiments" / "historical"))
    import run as HR
    assert HR.EXIT_POLICIES == (HR.NEURAL_OR_HORIZON, HR.FIXED_HOLD)
    with pytest.raises(SystemExit) as exc:
        HR.run_branch(name="x", cfg={}, series={}, parts=(), partitions=[],
                      run=None, mb=None, enc=None, pops=None, sha="",
                      policy_for=None, run_id="x", learn_in=set(),
                      start_gain=None, exit_policy="close_when_it_feels_right")
    assert "unknown exit_policy" in str(exc.value)


# ------------------- §6.3  one target: outcome == the Hold label -------

@requires_real_graph
def test_the_realised_fixed_hold_outcome_equals_the_evaluator_label(
        mb, series_a, tmp_path):
    """The §3 invariant, on the loop's own outcomes, at 1e-9."""
    day = DAYS[2]
    u = usable(series_a, day)
    script = {u[0]: "BUY", u[15]: "BUY", u[35]: "BUY", u[3]: "SELL",
              u[18]: "SELL"}
    out, journal, accounts, _, _ = run(mb, series_a, tmp_path, script,
                                       policy=FIXED_HOLD)
    notional, fee, slip = 1000.0, 5.0, 5.0

    logged = {e["episode_id"]: e for e in outcomes(journal)}
    realised = [o for o in accounts["LEARNING"].outcomes
                if o.close_reason is X.CloseReason.POLICY_CLOSE_FIXED_HOLD]
    assert len(realised) >= 2, "the fixture must produce exact-H closures"

    worst_live = worst_logged = 0.0
    for o in realised:
        decision_minute = o.entry.bar_index - 1
        h = HZ.hold(series_a, day, decision_minute, Hf, delay=1)
        assert h.ok, h.reason
        assert h.entry_minute == o.entry.bar_index
        assert h.exit_minute == o.exit.bar_index
        assert h.entry_open == o.entry.reference_price
        assert h.exit_open == o.exit.reference_price
        label = h.net_pnl(notional=notional, fee_bps=fee, slippage_bps=slip)
        worst_live = max(worst_live, abs(label - o.net_pnl))
        worst_logged = max(worst_logged,
                           abs(label - float(logged[o.episode_id]["net_pnl"])))

    # on the realised outcome itself the two computations agree in float
    assert worst_live <= 1e-9, f"max |realised - label| = {worst_live}"
    # the event log stores net_pnl rounded to 8 decimals, so a comparison read
    # back from it can differ by half of the last recorded digit and no more.
    # That is the recording precision, not a difference between the policies.
    assert worst_logged <= 5e-9, f"max |logged - label| = {worst_logged}"


@requires_real_graph
def test_the_anchor_is_the_entry_fill_minute_not_the_decision_minute(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    _, journal, _, _, _ = run(mb, series_a, tmp_path, {u[0]: "BUY"},
                              policy=FIXED_HOLD)
    o = outcomes(journal)[0]
    entry, exit_ = o["entry"]["bar_index"], o["exit"]["bar_index"]
    assert entry == u[0] + 1                        # decision + delay
    assert exit_ == entry + Hf                      # entry fill + H
    assert exit_ != u[0] + Hf                       # not decision + H
    assert exit_ != u[0] + 1 + Hf + 1               # no second delay
    assert o["exit"]["flag"] == ""                  # landed where asked


# ------------------------------ §6.4  reinforcement --------------------

@requires_real_graph
def test_one_completed_episode_makes_one_update_attributed_to_the_entry(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {u[0]: "BUY", u[2]: "SELL", u[4]: "SELL", u[20]: "BUY"}
    _, journal, _, credit, _ = run(mb, series_a, tmp_path, script,
                                   policy=FIXED_HOLD)

    ex = {e["episode_id"] for e in events(journal, "EXECUTION")}
    oc = [e["episode_id"] for e in outcomes(journal)]
    lr = [e["episode_id"] for e in events(journal, "LEARNING")]
    assert len(oc) == len(set(oc)) == len(ex)       # one outcome per episode
    assert lr == oc                                 # one update per outcome
    assert set(lr) <= ex                            # never for a non-entry
    assert credit.accepted == len(lr)
    for e in events(journal, "LEARNING"):
        assert e["accepted"] is True
        assert e["eligibility_source"] == "replayed_from_decision"
        assert e["k"] == 8 and e["normalisation"] == "mean_of_deltas"
        assert e["synapses_depressed"] > 0
    # the blocked SELL minutes produced no learning event of their own
    blocked_ids = {e["episode_id"] for e in events(journal, "DECISION")
                   if (e.get("rejection") or {}).get("reason")
                   == X.RejectReason.FIXED_HOLD.value}
    assert blocked_ids and not (blocked_ids & set(lr))
    # one dopamine event per episode, no repeats for one open position
    assert mb.events["reward"] + mb.events["punish"] == len(lr)


@requires_real_graph
def test_a_later_observation_cannot_receive_the_entrys_reward(
        mb, series_a, tmp_path):
    """The update is addressed to the entry's episode, not to the exit's."""
    u = usable(series_a, DAYS[2])
    _, journal, _, _, _ = run(mb, series_a, tmp_path, {u[0]: "BUY"},
                              policy=FIXED_HOLD)
    entry = events(journal, "EXECUTION")[0]
    learn = events(journal, "LEARNING")[0]
    assert learn["episode_id"] == entry["episode_id"]

    decisions = events(journal, "DECISION")
    during = [e for e in decisions
              if entry["bar_index"] <= e["bar_index"]
              <= outcomes(journal)[0]["exit"]["bar_index"]
              and e["episode_id"] != entry["episode_id"]]
    assert during, "the fixture must observe while the position is open"
    assert learn["episode_id"] not in {e["episode_id"] for e in during}


@requires_real_graph
def test_no_learning_event_exists_for_an_episode_without_an_outcome(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {m: "WAIT" for m in u}
    script[u[0]] = "BUY"
    _, journal, _, _, _ = run(mb, series_a, tmp_path, script,
                              policy=FIXED_HOLD)
    decided = {e["episode_id"] for e in events(journal, "DECISION")}
    settled = {e["episode_id"] for e in outcomes(journal)}
    learned = {e["episode_id"] for e in events(journal, "LEARNING")}
    assert learned == settled
    assert decided - settled                       # most rounds settle nothing
    assert not (learned & (decided - settled))


# ------------------- §6.5  session and partition boundaries ------------

def test_the_clock_rule_at_h_90_is_the_evaluators_clock_rule():
    """H = 90, the wave's own horizon: one rule, two callers, 390 minutes."""
    pol = H.HistoricalExecution({}, horizon_minutes=90, delay_minutes=1)
    last = None
    for m in range(H.SESSION_MINUTES):
        a = pol.eligible_to_enter(m)
        b = HZ.eligible(m, 90, delay=1)
        assert a == b, m
        if a:
            last = m
    assert last == 298                              # (298+1)+1+90 == 390
    assert pol.eligible_to_enter(298) and not pol.eligible_to_enter(299)
    assert H.SESSION_MINUTES == HZ.SESSION_MINUTES == 390


@requires_real_graph
def test_nothing_crosses_a_session_boundary_under_fixed_hold(
        mb, series_a, tmp_path):
    """A hold that cannot finish inside its session is closed inside it."""
    days = (DAYS[1], DAYS[2])
    u1 = usable(series_a, days[0])
    late = u1[-3]                                   # too late to reach +H
    _, journal, accounts, _, _ = run(
        mb, series_a, tmp_path, {late: "BUY"}, policy=FIXED_HOLD, days=days,
        horizon=90)

    oc = outcomes(journal)
    assert oc, "the fixture must open at least one position"
    for o in oc:
        entry_day = H.session_date(int(o["entry"]["ts"]))
        exit_day = H.session_date(int(o["exit"]["ts"]))
        # every hold that cannot finish inside its session ends inside it
        assert entry_day == exit_day
        assert entry_day in days
        assert o["exit"]["flag"] == H.SESSION_CLOSE_FILL
        # an exceptional closure keeps its own label; it is not exact-H
        assert o["close_reason"] == X.CloseReason.POLICY_CLOSE.value
        assert o["market_minutes_held"] < 90
    assert H.session_date(int(oc[0]["exit"]["ts"])) == days[0]
    assert oc[0]["exit"]["bar_index"] <= max(u1)
    # the next session started flat — HistoricalExecution.start_session
    # raises if anything crossed, so reaching here is the assertion
    assert accounts["LEARNING"].account.position is None


# ---------------------------- §6.6  crash and restart ------------------

@requires_real_graph
def test_a_restart_inside_a_fixed_hold_branch_duplicates_nothing(
        mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {u[0]: "BUY", u[15]: "BUY", u[30]: "BUY", u[45]: "BUY"}
    out, journal, _, _, _ = run(mb, series_a, tmp_path, script,
                                policy=FIXED_HOLD, restart_after=1)
    assert len(out["restarts"]) == 1
    assert out["restarts"][0]["gains_restored_exactly"] is True
    oc = [e["episode_id"] for e in outcomes(journal)]
    lr = [e["episode_id"] for e in events(journal, "LEARNING")]
    assert len(oc) >= 2
    assert oc == lr
    assert len(oc) == len(set(oc))                  # nothing applied twice


@requires_real_graph
@pytest.mark.parametrize("fault", REC.FAULT_POINTS)
def test_a_crash_at_any_fault_point_applies_one_fixed_hold_update(
        mb, series_a, tmp_path, fault, graph_sha256):
    """The D4 crash pattern, on a POLICY_CLOSE_FIXED_HOLD outcome.

    The recovery contract is the journal's own: ``recover`` restores the
    checkpoint and says what it did, and when it reports ``reapplied`` the
    caller replays the stored trace. Either way the weights must end at
    **exactly one** normalised application of the update, and the log must
    hold exactly one OUTCOME and one LEARNING for the episode.
    """
    from flytrade import runner as R
    u = usable(series_a, DAYS[2])
    store = tmp_path / f"fault-{fault}"

    # a real fixed-hold episode, so the outcome replayed below is one the
    # loop actually produced under this exit policy
    _, journal, _, _, _ = run(mb, series_a, tmp_path, {u[0]: "BUY"},
                              policy=FIXED_HOLD, name=f"seed-{fault}")
    settled = outcomes(journal)[0]
    assert settled["close_reason"] == \
        X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value
    ep = int(settled["episode_id"])

    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()
    versions = REC.Versions(market="m", encoder="e", runner=R.VERSION,
                            decoder="d",
                            execution=H.HistoricalExecution.version,
                            mushroom="mb", graph_sha256=graph_sha256)
    traces = SC.ScriptedRunner(mb)._traces(ep, 8)
    valence, amount = -1, 0.8

    # what exactly one normalised application must produce
    g0 = mb.gain.astype(np.float64)
    dense = np.zeros(len(mb.trace), dtype=np.float64)
    deltas = []
    for t in traces.traces:
        dense[:] = 0.0
        dense[t.index] = t.value
        deltas.append(mb.proposed_gain_delta(valence, amount, dense, gain=g0)[0])
    expected = np.clip(g0 + np.mean(deltas, axis=0), mb.floor,
                       1.0).astype(np.float32)
    before = mb.gain.copy()

    j2 = REC.Journal(store, mb=mb, credit=R.CreditAssigner(mb),
                     versions=versions)
    j2.save_checkpoint(last_settled_episode=-1)
    j2.credit.open_episode(traces)
    REC.write_pending(j2.pending_path, episode_id=ep, symbol="A",
                      stable_id=0, trace=traces, decision_bar=u[0],
                      graph_sha256=graph_sha256)

    with pytest.raises(REC.InjectedFault):
        j2.settle(ep, {"close_reason": settled["close_reason"],
                       "net_pnl": settled["net_pnl"], "symbol": "A"},
                  valence, amount, fault=fault)

    # --- restart: nothing in memory, everything from disk ---------------
    mb.gain[:] = 0.0
    mb.apply()
    fresh = R.CreditAssigner(mb)
    j3 = REC.Journal(store, mb=mb, credit=fresh, versions=versions)
    report = j3.recover()
    assert report["checkpoint_loaded"]
    if report["reapplied"]:
        assert report["pending_k"] == 8
        ev = fresh.settle(ep, valence, amount)
        assert ev.accepted and ev.k == 8
        assert ev.normalisation == "mean_of_deltas"
        j3.save_checkpoint(last_settled_episode=ep)
        REC.clear_pending(j3.pending_path)
        j3.log.append(REC.EventType.LEARNING,
                      {"episode_id": ep, **ev.as_dict()})

    final = mb.gain.copy()
    assert not np.array_equal(final, before), "the outcome was lost"
    assert np.allclose(final, expected, atol=1e-6), (
        "the outcome was applied a number of times other than once")

    evs = j3.log.read()
    assert len([e for e in evs if e["kind"] == "OUTCOME"
                and e["episode_id"] == ep]) == 1
    assert len([e for e in evs if e["kind"] == "LEARNING"
                and e["episode_id"] == ep]) == 1
    assert REC.read_pending(j3.pending_path) is None
    assert j3.last_settled_episode == ep

    # a second attempt on the same episode is refused, by name
    again = fresh.settle(ep, valence, amount, trace=traces)
    assert not again.accepted
    assert again.reason == R.RejectionReason.ALREADY_SETTLED.value
    assert np.array_equal(mb.gain, final)


# ------------------------------- §6.7  frozen weights ------------------

@requires_real_graph
def test_a_frozen_fixed_hold_branch_moves_no_weight(mb, series_a, tmp_path):
    u = usable(series_a, DAYS[2])
    script = {u[0]: "BUY", u[2]: "SELL", u[20]: "BUY"}
    gain0 = np.full(len(mb.pos), 0.7, dtype=np.float32)   # a learned state
    out, journal, _, credit, _ = run(
        mb, series_a, tmp_path, script, policy=FIXED_HOLD, learning=False,
        name="frozen", start_gain=gain0)

    p = out["partitions"]["LEARNING"]
    assert p["start_digest"] == p["end_digest"]
    assert p["digest_unchanged"] is True
    assert events(journal, "LEARNING") == []
    assert credit.accepted == 0
    assert journal.frozen_settled == len(outcomes(journal)) >= 1
    assert np.array_equal(mb.gain, gain0)
    for e in outcomes(journal):
        assert e["settlement"] == "SETTLED_FROZEN"
        assert e["close_reason"] == \
            X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value
    tally = p["tally"]["after_execution_constraints"]
    assert tally["SETTLED_FROZEN"] == len(outcomes(journal))


# ------------------------------- the two enum members ------------------

def test_the_two_new_members_are_named_and_distinct():
    assert X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value == \
        "POLICY_CLOSE_FIXED_HOLD"
    assert X.RejectReason.FIXED_HOLD.value == "FIXED_HOLD"
    assert X.CloseReason.POLICY_CLOSE_FIXED_HOLD is not X.CloseReason.POLICY_CLOSE
    assert X.CloseReason.POLICY_CLOSE_FIXED_HOLD not in (
        X.CloseReason.NEURAL_SELL, X.CloseReason.END_OF_DATA)
    # both horizon closures settle at the anchor, a decided exit does not
    assert H.POLICY_CLOSURES == (X.CloseReason.POLICY_CLOSE,
                                 X.CloseReason.POLICY_CLOSE_FIXED_HOLD)
    assert X.CloseReason.NEURAL_SELL not in H.POLICY_CLOSURES
