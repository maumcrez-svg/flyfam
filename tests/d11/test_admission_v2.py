"""``admission_v2``: the recency rule, its boundaries, and its four silences.

Owner bullets 1–9. Tapes are scripted (``tests.d11.fixtures``, whose numbers are
invented and labelled as such). The admission code, the curve quote, the tape
reconstruction and the rotation key are real.
"""

from __future__ import annotations

import pytest

from flytrade.pons.admission_v2 import (COLLECTOR_LAG, COVERAGE,
                                        CURVE_EXHAUSTED, DATA_LAG,
                                        DEPLOYMENT_UNSUPPORTED, INACTIVE,
                                        INSUFFICIENT_HISTORY,
                                        NO_ELIGIBLE_CANDIDATES,
                                        QUOTE_UNSUPPORTED, ROTATED,
                                        ROUTE_COMPLETED, STATE_INVALID,
                                        AdmissionPolicyV2)
from flytrade.pons.context_v2 import context_v2
from tests.d11 import fixtures as F


def policy(**kw) -> AdmissionPolicyV2:
    return AdmissionPolicyV2(**kw)


def consider(pol, tape, cutoff, stable_id=0):
    return pol.consider(tape, context_v2(tape, cutoff, stable_id=stable_id),
                        stable_id=stable_id, cutoff=cutoff)


# ------------------------------------------- bullet 1: recency boundaries
def test_two_trades_in_the_window_with_the_last_inside_the_bound_is_admitted():
    tape = F.traded_at((20, 250, 290))          # read at 300: 250 s and 290 s
    candidate = consider(policy(), tape, tape.launched_at + 300)
    assert candidate.admitted and candidate.reasons == ()


def test_the_recent_count_boundary_is_exact():
    """Two trades in the window admits; one does not, and says `INACTIVE`."""
    pol = policy()
    cutoff_offset = 300
    two = F.traded_at((20, 250, 290))
    one = F.traded_at((20, 40, 290))            # only 290 s lies in the window
    assert consider(pol, two, two.launched_at + cutoff_offset).admitted
    thin = consider(pol, one, one.launched_at + cutoff_offset)
    assert not thin.admitted and INACTIVE in thin.reasons


def test_the_window_edge_is_half_open_at_the_start():
    """A trade exactly ``recent_window_seconds`` back is outside the window."""
    pol = policy(recent_window_s=120, min_valid_trades_in_window=2,
                 max_seconds_since_last_trade=60)
    cutoff = F.FIRST_TS + 300
    # trades at 180 s (exactly 120 s back) and 181 s and 290 s
    edge = F.traded_at((20, 180, 181, 290))
    ctx = context_v2(edge, cutoff)
    assert ctx.raw["trade_count_2m"] == 2.0, "the 120 s-old trade is excluded"
    assert consider(pol, edge, cutoff).admitted


def test_the_recency_boundary_is_inclusive_at_exactly_sixty_seconds():
    pol = policy()
    cutoff = F.FIRST_TS + 300
    at_bound = F.traded_at((20, 200, 240))      # last trade exactly 60 s back
    assert context_v2(at_bound, cutoff).raw["since_last_trade"] == 60.0
    assert consider(pol, at_bound, cutoff).admitted
    past_bound = F.traded_at((20, 200, 239))    # 61 s back
    candidate = consider(pol, past_bound, cutoff)
    assert not candidate.admitted and INACTIVE in candidate.reasons


def test_a_long_quiet_tape_is_inactive_and_not_insufficient_history():
    tape = F.quiet_tape()
    candidate = consider(policy(), tape, tape.launched_at + 600)
    assert not candidate.admitted
    assert INACTIVE in candidate.reasons
    assert INSUFFICIENT_HISTORY not in candidate.reasons


def test_a_token_below_the_minimum_age_is_insufficient_history_not_inactive():
    tape = F.traded_at((5, 10, 20))
    candidate = consider(policy(), tape, tape.launched_at + 30)
    assert not candidate.admitted
    assert INSUFFICIENT_HISTORY in candidate.reasons
    assert INACTIVE not in candidate.reasons


def test_v2_admits_a_token_v1_refuses_for_having_only_two_trades_ever():
    """The clause v2 removes: 'at least three trades ever'."""
    from flytrade.pons.admission import UNUSABLE, AdmissionPolicy
    tape = F.traded_at((250, 290))
    cutoff = tape.launched_at + 300
    v1 = AdmissionPolicy().consider(tape, tape.context(cutoff), stable_id=0,
                                    cutoff=cutoff)
    assert not v1.admitted and UNUSABLE in v1.reasons
    assert consider(policy(), tape, cutoff).admitted


# ----------------------------------- bullet 2: buys and sells count alike
def test_buys_and_sells_are_counted_symmetrically():
    buys = F.traded_at((20, 250, 290))
    sells = F.traded_at((20, 250, 290), sells={250, 290})
    mixed = F.traded_at((20, 250, 290), sells={290})
    cutoff_offset = 300
    for tape in (buys, sells, mixed):
        ctx = context_v2(tape, tape.launched_at + cutoff_offset)
        assert ctx.raw["trade_count_2m"] == 2.0
        assert consider(policy(), tape, tape.launched_at + cutoff_offset).admitted


def test_a_sell_alone_can_satisfy_the_recency_rule():
    tape = F.traded_at((20, 40, 250, 290), sells={250, 290})
    assert consider(policy(), tape, tape.launched_at + 300).admitted


# ------------------------------------------ bullet 3: no future admission
def test_no_future_event_can_admit_a_candidate():
    """A tape that trades *after* the cutoff is inactive *at* the cutoff."""
    tape = F.traded_at((20, 40, 400, 430))
    quiet_cutoff = tape.launched_at + 300
    candidate = consider(policy(), tape, quiet_cutoff)
    assert not candidate.admitted and INACTIVE in candidate.reasons


def test_feeding_the_tape_more_history_than_the_cutoff_covers_changes_nothing():
    short = F.traded_at((20, 250, 290))
    long = F.traded_at((20, 250, 290, 400, 500, 600))
    cutoff = F.FIRST_TS + 300
    a = context_v2(short, cutoff)
    b = context_v2(long, cutoff)
    assert a.raw == b.raw
    assert consider(policy(), short, cutoff).reasons == \
        consider(policy(), long, cutoff).reasons


# ------------------------------------- bullet 4: duplicates and reverted
def test_a_duplicated_log_is_counted_once():
    tape = F.traded_at((20, 290))
    event = F.buy_event(tape.curve, at_seconds=290, quote_in=F.QUOTE,
                        state=tape.state, log_index=1)
    tape.apply(F.duplicate_of(tape, event))
    cutoff = tape.launched_at + 300
    assert context_v2(tape, cutoff).raw["trade_count_2m"] == 1.0, \
        "the same log id must not be counted twice"
    candidate = consider(policy(), tape, cutoff)
    assert not candidate.admitted and INACTIVE in candidate.reasons


def test_an_event_that_never_reached_the_tape_cannot_be_counted():
    """Orphaned and removed logs never reach ``TokenTape.apply``.

    The collector drops a log whose status is not OK before the loop sees it,
    so the tape a context is computed from contains only accepted events. This
    asserts the consequence: the two tapes differ by exactly the event that was
    never applied, and the recency rule reads the one that was.
    """
    kept = F.traded_at((20, 250, 290))
    dropped = F.traded_at((20, 250))
    cutoff = F.FIRST_TS + 300
    assert context_v2(kept, cutoff).raw["trade_count_2m"] == 2.0
    assert context_v2(dropped, cutoff).raw["trade_count_2m"] == 1.0
    assert consider(policy(), kept, cutoff).admitted
    assert not consider(policy(), dropped, cutoff).admitted


def test_a_zero_amount_trade_is_not_a_valid_trade():
    """Neither leg may be zero, and the launch point is not a trade."""
    from flytrade.pons.context import TapePoint
    from flytrade.pons.context_v2 import is_valid_trade, valid_trades

    def point(kind, price, log_id=""):
        return TapePoint(ts=F.FIRST_TS + 290, block_number=1, kind=kind,
                         quote_reserve=1, token_reserve=1,
                         real_quote_reserve=1, sellable_tokens=1,
                         graduated=False, flow=1, trade_price=price,
                         log_id=log_id)

    assert is_valid_trade(point("CurveBuy", 1.7e-09))
    assert is_valid_trade(point("CurveSell", 1.7e-09))
    assert not is_valid_trade(point("CurveBuy", None)), "zero token leg"
    assert not is_valid_trade(point("CurveBuy", 0.0)), "zero quote leg"
    assert not is_valid_trade(point("launch", None))
    assert not is_valid_trade(point("CurveCompleted", None))
    same = [point("CurveBuy", 1.7e-09, log_id="0xabc"),
            point("CurveBuy", 1.7e-09, log_id="0xabc")]
    assert len(valid_trades(same)) == 1, "deduplicated by log id"


def test_a_malformed_trade_makes_the_whole_tape_unusable_not_merely_uncounted():
    """A leg that does not reproduce the curve's arithmetic is never priced."""
    tape = F.traded_at((20, 250))
    event = F.buy_event(tape.curve, at_seconds=290, quote_in=F.QUOTE,
                        state=tape.state, log_index=7)
    event["args"]["tokensOut"] = "0"
    tape.apply(event)
    cutoff = tape.launched_at + 300
    assert tape.inconsistent
    candidate = consider(policy(), tape, cutoff)
    assert not candidate.admitted and STATE_INVALID in candidate.reasons


# ----------------------------------------- bullet 5: reversible readmission
def test_admission_is_reversible():
    """Inactive at one cutoff, admitted again at the next, on the same object."""
    pol = policy()
    tape = F.traded_at((20, 40, 250, 290, 700, 730))
    quiet = tape.launched_at + 500
    later = tape.launched_at + 740
    assert consider(pol, tape, tape.launched_at + 300).admitted
    gone = consider(pol, tape, quiet)
    assert not gone.admitted and INACTIVE in gone.reasons
    back = consider(pol, tape, later)
    assert back.admitted, "new qualifying activity must readmit the candidate"


def test_nothing_about_a_past_exclusion_is_remembered():
    """Two policies, one of which saw the quiet tick, agree at the later tick."""
    cold = policy()
    warm = policy()
    tape = F.traded_at((20, 40, 250, 290, 700, 730))
    consider(warm, tape, tape.launched_at + 500)
    later = tape.launched_at + 740
    assert consider(cold, tape, later).reasons == consider(warm, tape, later).reasons


# ------------------------------------------- bullet 6: no stale fallback
def test_fewer_than_six_qualifying_candidates_are_presented_as_they_are():
    pol = policy()
    tapes = [F.traded_at((20, 250, 290), token=f"0x{i:040x}",
                         curve=f"0x{i + 100:040x}") for i in range(3)]
    candidates = [consider(pol, t, t.launched_at + 300, stable_id=i)
                  for i, t in enumerate(tapes)]
    presented, omitted = pol.rotate(candidates, round_index=1)
    assert len(presented) == 3 and omitted == []


def test_an_inactive_candidate_is_never_used_to_fill_a_slot():
    pol = policy()
    active = [F.traded_at((20, 250, 290), token=f"0x{i:040x}",
                          curve=f"0x{i + 100:040x}") for i in range(2)]
    stale = [F.quiet_tape(token=f"0x{i + 50:040x}", curve=f"0x{i + 150:040x}")
             for i in range(4)]
    candidates = [consider(pol, t, t.launched_at + 300, stable_id=i)
                  for i, t in enumerate(active + stale)]
    presented, _ = pol.rotate(candidates, round_index=1)
    assert len(presented) == 2, "the four stale candidates must not fill the round"


def test_a_round_with_nothing_eligible_is_named_and_not_relaxed():
    pol = policy()
    stale = [F.quiet_tape(token=f"0x{i:040x}", curve=f"0x{i + 100:040x}")
             for i in range(4)]
    candidates = [consider(pol, t, t.launched_at + 600, stable_id=i)
                  for i, t in enumerate(stale)]
    presented, _ = pol.rotate(candidates, round_index=1)
    assert presented == []
    assert pol.empty_round_status(candidates) == NO_ELIGIBLE_CANDIDATES


# --------------------------------- bullet 7: a collector gap is not silence
def test_a_collector_gap_is_collector_lag_and_never_inactive():
    cutoff = F.FIRST_TS + 300
    tape = F.traded_at((20, 250, 290))
    lagging = policy(data_as_of=cutoff - 61)
    candidate = lagging.consider(tape, context_v2(tape, cutoff), stable_id=0,
                                 cutoff=cutoff)
    assert not candidate.admitted
    assert COLLECTOR_LAG in candidate.reasons
    assert INACTIVE not in candidate.reasons, \
        "our data being late is not the token going quiet"


def test_a_quiet_token_under_a_collector_gap_is_not_called_inactive_either():
    cutoff = F.FIRST_TS + 600
    tape = F.quiet_tape()
    lagging = policy(data_as_of=cutoff - 200)
    candidate = lagging.consider(tape, context_v2(tape, cutoff), stable_id=0,
                                 cutoff=cutoff)
    assert COLLECTOR_LAG in candidate.reasons
    assert INACTIVE not in candidate.reasons


def test_data_as_of_inside_the_bound_does_not_lag():
    cutoff = F.FIRST_TS + 300
    tape = F.traded_at((20, 250, 290))
    fresh = policy(data_as_of=cutoff - 60)
    assert fresh.consider(tape, context_v2(tape, cutoff), stable_id=0,
                          cutoff=cutoff).admitted


def test_replay_can_never_lag():
    assert policy().data_as_of is None
    assert not policy().lagging(F.FIRST_TS + 10_000)


def test_a_whole_tracked_set_behind_the_collector_is_DATA_LAG_not_a_sea_of_inactive():
    cutoff = F.FIRST_TS + 600
    pol = policy(data_as_of=cutoff - 200)
    tapes = [F.quiet_tape(token=f"0x{i:040x}", curve=f"0x{i + 100:040x}")
             for i in range(5)]
    candidates = [pol.consider(t, context_v2(t, cutoff), stable_id=i,
                               cutoff=cutoff) for i, t in enumerate(tapes)]
    assert pol.empty_round_status(candidates) == DATA_LAG
    assert all(INACTIVE not in c.reasons for c in candidates)


def test_a_mixed_round_is_not_data_lag():
    """One token excluded for its own reason means the collector is not the story."""
    cutoff = F.FIRST_TS + 600
    pol = policy()
    tapes = [F.quiet_tape(token=f"0x{i:040x}", curve=f"0x{i + 100:040x}")
             for i in range(3)]
    candidates = [pol.consider(t, context_v2(t, cutoff), stable_id=i,
                               cutoff=cutoff) for i, t in enumerate(tapes)]
    assert pol.empty_round_status(candidates) == NO_ELIGIBLE_CANDIDATES


# ------------------------------------------------ bullet 9: invariance
def test_the_verdict_does_not_depend_on_the_address():
    cutoff = F.FIRST_TS + 300
    one = F.traded_at((20, 250, 290), token="0x" + "a" * 40,
                      curve="0x" + "b" * 40)
    two = F.traded_at((20, 250, 290), token="0x" + "c" * 40,
                      curve="0x" + "d" * 40)
    assert (consider(policy(), one, cutoff).admitted
            == consider(policy(), two, cutoff).admitted)


def test_the_verdict_does_not_depend_on_the_stable_id_or_the_iteration_order():
    pol = policy()
    cutoff = F.FIRST_TS + 300
    tapes = [F.traded_at((20, 250, 290), token=f"0x{i:040x}",
                         curve=f"0x{i + 100:040x}") for i in range(4)]
    forward = [consider(pol, t, cutoff, stable_id=i).reasons
               for i, t in enumerate(tapes)]
    backward = list(reversed(
        [consider(pol, t, cutoff, stable_id=i).reasons
         for i, t in reversed(list(enumerate(tapes)))]))
    assert forward == backward


def test_the_recorded_policy_names_its_own_constants():
    d = policy().as_dict()
    assert d["version"] == "admission_v2"
    assert d["recent_window_seconds"] == 120
    assert d["minimum_valid_trades_in_window"] == 2
    assert d["maximum_seconds_since_last_trade"] == 60
    for code in (INACTIVE, INSUFFICIENT_HISTORY, COLLECTOR_LAG,
                 QUOTE_UNSUPPORTED, ROUTE_COMPLETED, STATE_INVALID, COVERAGE,
                 CURVE_EXHAUSTED, DEPLOYMENT_UNSUPPORTED, ROTATED):
        assert code in d["reason_codes"]


def test_the_reason_codes_are_all_distinct_and_none_is_a_readout_status():
    from flytrade import decoder as D
    from flytrade.pons.admission_v2 import REASON_CODES
    assert len(set(REASON_CODES)) == len(REASON_CODES)
    readout = {s.value for s in D.ReadoutStatus}
    assert not (set(REASON_CODES) & readout)
    assert "NO_RESPONSE" not in REASON_CODES


# --------------------------------------- the v1 clauses that stay unchanged
def test_the_v1_clauses_keep_their_own_names():
    cutoff = F.FIRST_TS + 300
    tape = F.traded_at((20, 250, 290))
    object.__setattr__(tape, "quote_asset", "0x" + "d" * 40)
    assert QUOTE_UNSUPPORTED in consider(policy(), tape, cutoff).reasons

    other = F.traded_at((20, 250, 290))
    other.deployment = "pons-v1"
    assert DEPLOYMENT_UNSUPPORTED in consider(policy(), other, cutoff).reasons

    short = F.traded_at((20, 250, 290), coverage_seconds=400)
    assert COVERAGE in consider(policy(), short, cutoff).reasons

    done = F.traded_at((20, 250, 290))
    done.apply(F.completed_event(done.curve, at_seconds=295))
    assert ROUTE_COMPLETED in consider(policy(), done, cutoff).reasons


def test_an_exhausting_buy_is_refused_with_its_own_code():
    cutoff = F.FIRST_TS + 300
    tape = F.traded_at((20, 250, 290))
    huge = policy(size_wei=10 ** 24)
    candidate = huge.consider(tape, context_v2(tape, cutoff), stable_id=0,
                              cutoff=cutoff)
    assert not candidate.admitted
    assert CURVE_EXHAUSTED in candidate.reasons or STATE_INVALID in candidate.reasons
