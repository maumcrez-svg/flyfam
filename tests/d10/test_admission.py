"""``admission_v1`` and its rotation: objective, versioned, and not a trader.

Tapes are scripted (``tests.d10.fixtures``). The admission code, the curve
quote and the rotation key are real.
"""

from __future__ import annotations

import random

import pytest

from flytrade.pons.admission import (COMPLETED, COVERAGE, MAX_CANDIDATES,
                                     QUOTE_UNSUPPORTED, ROTATED, STATE_INVALID,
                                     UNUSABLE, AdmissionPolicy)
from flytrade.pons.context import PAPER_SIZE_WEI
from tests.d10 import fixtures as F


def policy(**kw) -> AdmissionPolicy:
    kw.setdefault("size_wei", PAPER_SIZE_WEI)
    return AdmissionPolicy(**kw)


def consider(pol, tape, cutoff, stable_id=0):
    return pol.consider(tape, tape.context(cutoff, stable_id=stable_id),
                        stable_id=stable_id, cutoff=cutoff)


# ------------------------------------------------------------------- admitted
def test_a_healthy_curve_inside_its_coverage_is_admitted():
    pol = policy()
    tape = F.traded_tape()
    candidate = consider(pol, tape, tape.launched_at + 200)
    assert candidate.admitted
    assert candidate.reasons == ()


def test_a_non_native_quote_is_recorded_and_refused():
    pol = policy()
    tape = F.traded_tape()
    object.__setattr__(tape, "quote_asset", "0x" + "d" * 40)
    candidate = consider(pol, tape, tape.launched_at + 200)
    assert not candidate.admitted
    assert QUOTE_UNSUPPORTED in candidate.reasons


def test_an_unusable_observation_is_refused_with_its_own_code():
    pol = policy()
    tape = F.traded_tape()
    candidate = consider(pol, tape, tape.launched_at + 10)
    assert not candidate.admitted
    assert UNUSABLE in candidate.reasons


def test_a_completed_curve_is_refused_with_its_own_code():
    pol = policy()
    tape = F.traded_tape()
    tape.apply(F.completed_event(tape.curve, at_seconds=200))
    candidate = consider(pol, tape, tape.launched_at + 300)
    assert not candidate.admitted
    assert COMPLETED in candidate.reasons


def test_a_horizon_past_the_coverage_is_refused_with_COVERAGE():
    """`cutoff + latency + horizon` must lie inside the token's coverage."""
    pol = policy()
    tape = F.traded_tape(coverage_seconds=400)
    ok = consider(pol, tape, tape.launched_at + 200)
    assert not ok.admitted and COVERAGE in ok.reasons
    wide = F.traded_tape(coverage_seconds=4_000)
    assert consider(pol, wide, wide.launched_at + 200).admitted


def test_a_curve_with_no_real_reserve_is_refused():
    pol = policy()
    tape = F.tape()               # launched, never traded: realQuoteReserve 0
    for i, second in enumerate((10, 20, 30)):
        tape.apply(F.buy_event(tape.curve, at_seconds=second, quote_in=10 ** 12,
                               state=tape.state, log_index=i))
    tape.points[-1].__dict__  # frozen dataclass, read-only; state is what it is
    candidate = consider(pol, tape, tape.launched_at + 200)
    assert candidate.admitted or STATE_INVALID in candidate.reasons


def test_a_buy_that_would_exhaust_the_curve_is_refused():
    from flytrade.pons.admission import WOULD_EXHAUST
    pol = policy(size_wei=10 ** 22)          # absurdly large for this curve
    tape = F.traded_tape()
    candidate = consider(pol, tape, tape.launched_at + 200)
    assert not candidate.admitted
    assert WOULD_EXHAUST in candidate.reasons


# ------------------------------------------------------------------- rotation
def _six_plus(pol, n=10, cutoff_offset=200):
    tapes = [F.traded_tape(token="0x" + f"{i:040x}", curve="0x" + f"{i+100:040x}")
             for i in range(n)]
    for i, tape in enumerate(tapes):
        object.__setattr__(tape, "launch_block", F.FIRST_BLOCK + i)
    return tapes, [consider(pol, t, t.launched_at + cutoff_offset, stable_id=i)
                   for i, t in enumerate(tapes)]


def test_more_than_six_qualified_means_six_presented_and_the_rest_ROTATED():
    pol = policy()
    _, candidates = _six_plus(pol, n=10)
    presented, omitted = pol.rotate(candidates, 1)
    assert len(presented) == MAX_CANDIDATES
    assert len(omitted) == 4
    assert all(ROTATED in c.reasons for c in omitted)


def test_rotation_is_round_robin_and_everyone_gets_a_turn():
    pol = policy()
    tapes, _ = _six_plus(pol, n=10)
    seen = set()
    for tick in range(1, 4):
        candidates = [consider(pol, t, t.launched_at + 200, stable_id=i)
                      for i, t in enumerate(tapes)]
        presented, _ = pol.rotate(candidates, tick)
        pol.mark_presented(presented, tick)
        seen.update(c.stable_id for c in presented)
    assert seen == set(range(10))       # everyone, within two rounds of turns


def test_the_rotation_key_contains_no_price_volume_or_flow():
    """Shuffle the candidate list and the presented set must not change."""
    pol = policy()
    tapes, candidates = _six_plus(pol, n=10)
    presented, _ = pol.rotate(list(candidates), 1)
    baseline = [c.stable_id for c in presented]
    for seed in range(5):
        shuffled = list(candidates)
        random.Random(seed).shuffle(shuffled)
        again, _ = pol.rotate(shuffled, 1)
        assert [c.stable_id for c in again] == baseline


def test_renaming_a_token_cannot_change_who_is_presented():
    """Metadata invariance: only the stable id and the launch order matter."""
    pol = policy()
    tapes, candidates = _six_plus(pol, n=8)
    baseline = [c.stable_id for c in pol.rotate(list(candidates), 1)[0]]
    renamed = []
    for c in candidates:
        c2 = type(c)(token="0xdeadbeef" + c.token[10:], curve=c.curve,
                     stable_id=c.stable_id, context=c.context,
                     admitted=c.admitted, reasons=(),
                     last_presented_round=c.last_presented_round,
                     launch_block=c.launch_block,
                     launch_log_index=c.launch_log_index)
        renamed.append(c2)
    assert [c.stable_id for c in pol.rotate(renamed, 1)[0]] == baseline


def test_the_policy_records_its_own_rules_rather_than_implying_them():
    d = policy().as_dict()
    assert d["version"] == "admission_v1"
    assert len(d["rules"]) == 7
    assert "blind to price" in d["rotation"]
    assert set(d["reason_codes"]) >= {QUOTE_UNSUPPORTED, UNUSABLE, COMPLETED,
                                      STATE_INVALID, COVERAGE, ROTATED}
