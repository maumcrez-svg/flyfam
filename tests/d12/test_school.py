"""School mode: the maturity rule, the pending queue, and no lookahead.

Everything here is the arithmetic and the bookkeeping, tested without a brain:
:func:`school.maturity_cutoff` and :func:`school.grade_cohort` are the two
places where "when is a lesson applied" and "what does the cohort say" are
decided, and both are pure. The brain-side assertions — the determinism of the
first 100 ticks, the zero positions of the real run — are in
``test_artifacts.py``, which reads what the run wrote.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

import pytest

import school as SCH
from common import CADENCE, SETTLE_S
from flytrade.pons import reinforcement as RF

ROOT = Path(__file__).resolve().parents[2]
D12 = ROOT / "experiments" / "d12"
CONFIG = json.loads((D12 / "d12_001.json").read_text())

T0 = 1_789_229_564          # the recorded t0 of `d11-backfill-v1`
T = 1_789_259_804           # the recorded cutoff


# --------------------------------------------------------------- maturity
def test_a_lesson_can_never_mature_before_cutoff_plus_902():
    for k in range(0, 1009):
        cutoff = T0 + k * CADENCE
        assert SCH.maturity_cutoff(cutoff, T0) >= cutoff + SETTLE_S


def test_the_maturity_tick_is_on_the_grid_and_is_the_first_one_that_qualifies():
    for k in range(0, 1009):
        cutoff = T0 + k * CADENCE
        m = SCH.maturity_cutoff(cutoff, T0)
        assert (m - T0) % CADENCE == 0
        assert m - CADENCE < cutoff + SETTLE_S       # the *first* one


def test_on_this_grid_the_maturity_tick_is_always_cutoff_plus_930():
    """902 is not a multiple of 30, so the lesson is graded 28 s in the past."""
    for k in range(0, 1009):
        cutoff = T0 + k * CADENCE
        assert SCH.maturity_cutoff(cutoff, T0) == cutoff + 930
    assert 930 - SETTLE_S == 28


def test_a_lesson_inside_the_boundary_never_matures_at_a_frozen_tick():
    """cutoff + 902 <= T is exactly the rule that keeps maturity inside."""
    for k in range(0, 1009):
        cutoff = T0 + k * CADENCE
        if cutoff + SETTLE_S <= T:
            assert SCH.maturity_cutoff(cutoff, T0) <= T
        else:
            assert SCH.maturity_cutoff(cutoff, T0) > T


def test_the_pending_queue_is_bounded_by_the_maturity_lag():
    lag = (SCH.maturity_cutoff(T0, T0) - T0) // CADENCE
    assert lag == 31
    pending = {}
    for k in range(0, 200):
        cutoff = T0 + k * CADENCE
        pending.pop(cutoff, None)
        pending[SCH.maturity_cutoff(cutoff, T0)] = ["a lesson"]
        assert len(pending) <= lag


# ------------------------------------------------------------ the cohort
def lesson(stable_id, token=None):
    return {"stable_id": stable_id, "token": token or f"0x{stable_id:040x}",
            "cutoff_ts": T0, "tick": 1, "episode_id": stable_id,
            "valence_hz": 0.0}


def labels_for(pairs):
    """``{stable_id: label}`` from ``(stable_id, net_wei_or_None)`` pairs."""
    out = {}
    for stable_id, net in pairs:
        if net is None:
            out[stable_id] = {"settled": False, "reason": "ROUTE_TRANSITION:SELL"}
        else:
            out[stable_id] = {"settled": True, "net_wei": str(net),
                              "net": net / 1e18, "return_on_notional": 0.0}
    return out


def test_a_graded_cohort_carries_n_rank_and_s_and_is_in_stable_id_order():
    cohort = [lesson(7), lesson(2), lesson(5)]
    settled, dropped = grade(cohort, [(7, 300), (2, 100), (5, 200)])
    assert [r["stable_id"] for r in settled] == [2, 5, 7]
    assert [r["n"] for r in settled] == [3, 3, 3]
    assert [r["rank"] for r in settled] == [1.0, 2.0, 3.0]
    assert [r["s"] for r in settled] == [-1.0, 0.0, 1.0]
    assert dropped == Counter()


def grade(cohort, pairs, n_min=3):
    return SCH.grade_cohort(cohort, labels_for(pairs), n_min=n_min)


def test_an_unresolved_member_leaves_the_cohort_and_is_counted():
    cohort = [lesson(i) for i in (1, 2, 3, 4)]
    settled, dropped = grade(cohort, [(1, 10), (2, None), (3, 30), (4, 40)])
    assert [r["stable_id"] for r in settled] == [1, 3, 4]
    assert dropped[RF.UNRESOLVED] == 1
    assert all(r["n"] == 3 for r in settled)


def test_the_unresolved_drop_is_taken_before_n_is_computed():
    """n is the size *after* the drop, or the ranks would address a ghost."""
    cohort = [lesson(i) for i in (1, 2, 3, 4, 5)]
    settled, dropped = grade(cohort, [(1, 10), (2, None), (3, None),
                                      (4, 40), (5, 50)])
    assert dropped[RF.UNRESOLVED] == 2
    assert [r["n"] for r in settled] == [3, 3, 3]
    assert [r["s"] for r in settled] == [-1.0, 0.0, 1.0]


def test_a_cohort_below_n_min_teaches_nobody_and_is_counted():
    cohort = [lesson(i) for i in (1, 2)]
    settled, dropped = grade(cohort, [(1, 10), (2, 20)])
    assert settled == []
    assert dropped[RF.COHORT_TOO_SMALL] == 2


def test_a_cohort_that_drops_below_n_min_teaches_nobody():
    cohort = [lesson(i) for i in (1, 2, 3)]
    settled, dropped = grade(cohort, [(1, 10), (2, None), (3, 30)])
    assert settled == []
    assert dropped[RF.UNRESOLVED] == 1
    assert dropped[RF.COHORT_TOO_SMALL] == 2


def test_the_net_is_read_as_an_integer_so_two_equal_weis_tie_exactly():
    cohort = [lesson(i) for i in (1, 2, 3)]
    settled, _ = grade(cohort, [(1, 10 ** 16), (2, 10 ** 16), (3, 2 * 10 ** 16)])
    assert settled[0]["s"] == settled[1]["s"]
    assert isinstance(settled[0]["net_wei"], int)


def test_the_financial_net_and_the_signal_stay_two_columns():
    cohort = [lesson(i) for i in (1, 2, 3)]
    settled, _ = grade(cohort, [(1, -5), (2, -3), (3, -1)])
    assert all(r["net_wei"] < 0 for r in settled)     # everyone lost money
    assert [r["s"] for r in settled] == [-1.0, 0.0, 1.0]   # one still best


# ---------------------------------------------------- the school opens none
EXECUTION_VERBS = ("open_long", "due_for_horizon", "plan_buy", "plan_sell",
                   "_tick_flat", "_tick_holding", "_close_at_horizon",
                   "_reinforce", "open_episode", "record_decision")


def test_the_school_names_no_execution_verb_anywhere():
    """No position is opened, held, marked or closed — by construction."""
    text = (D12 / "school.py").read_text()
    tree = ast.parse(text)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    for verb in EXECUTION_VERBS:
        assert verb not in names, f"school.py calls {verb}"


def test_the_registration_says_the_school_holds_no_position():
    fixed = CONFIG["fixed_for_the_whole_wave"]
    assert fixed["max_open_positions_in_the_school"] == 0
    assert CONFIG["school_mode"]["no_position"].startswith(
        "the LEARNING branch opens no paper position")


def test_the_registered_maturity_rule_is_the_one_the_code_applies():
    rule = CONFIG["school_mode"]["maturity_rule"]
    assert "cutoff + 902" in rule and "930" in rule
    assert CONFIG["school_mode"]["application_order"].endswith(
        "BEFORE that tick's presentations")


def test_the_checkpoint_cadence_and_the_diagnostic_cadence_are_registered():
    assert SCH.CHECKPOINT_EVERY == 500
    assert SCH.DIAGNOSTIC_EVERY == 500
    assert "500" in CONFIG["records"]["checkpoint_cadence"]
