"""`relative_cohort_v1`: the owner's two examples, ties, n < 3, the selector.

The rule is the whole of what D12 changes, so every clause of PLAN.md §3 is
asserted here — including the two known answers, which were written into
``experiments/d12/d12_001.json`` at step (ii), **before** the rule ever ran on
the store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flytrade.pons import loop as LOOP
from flytrade.pons import reinforcement as RF

ROOT = Path(__file__).resolve().parents[2]
D12 = ROOT / "experiments" / "d12"
CONFIG = json.loads((D12 / "d12_001.json").read_text())

#: the owner's own two cohorts, in per-cent returns, best first
OWNER_EXAMPLE_1 = (14, 3, -2, -7, -18, -61)
OWNER_EXAMPLE_2 = (-3, -8, -15, -28, -50, -82)
OWNER_ANSWER = (1.0, 0.6, 0.2, -0.2, -0.6, -1.0)


# ------------------------------------------------------- the known answers
@pytest.mark.parametrize("cohort", [OWNER_EXAMPLE_1, OWNER_EXAMPLE_2])
def test_the_owners_two_examples_give_the_registered_signals(cohort):
    """+1, +0.6, +0.2, -0.2, -0.6, -1 — exactly, not to a tolerance."""
    assert tuple(RF.relative_cohort_signals(cohort)) == OWNER_ANSWER


def test_the_registered_file_carries_the_same_known_answer():
    block = CONFIG["reinforcement"][RF.RELATIVE_COHORT_V1]["known_answer"]
    assert tuple(block["owner_example_1_percent"]) == OWNER_EXAMPLE_1
    assert tuple(block["owner_example_2_percent"]) == OWNER_EXAMPLE_2
    assert tuple(block["s_for_both"]) == OWNER_ANSWER


def test_a_cohort_that_all_lost_money_still_teaches_which_lost_least():
    """The owner's point: the signal is relative and the net is not falsified."""
    losses = OWNER_EXAMPLE_2
    s = RF.relative_cohort_signals(losses)
    assert max(losses) == losses[0] and s[0] == 1.0
    assert min(losses) == losses[-1] and s[-1] == -1.0
    assert all(v < 0 for v in losses)          # nothing made money
    assert abs(sum(s)) < 1e-12                 # and the cohort mean is 0


def test_the_order_of_the_input_does_not_change_any_members_signal():
    cohort = list(OWNER_EXAMPLE_1)
    forward = dict(zip(cohort, RF.relative_cohort_signals(cohort)))
    backward = dict(zip(cohort[::-1],
                        RF.relative_cohort_signals(cohort[::-1])))
    assert forward == backward


# --------------------------------------------------------------- the shape
def test_the_worst_is_minus_one_the_best_is_plus_one_and_the_mean_is_zero():
    for n in range(3, 30):
        s = RF.relative_cohort_signals(list(range(n)))
        assert s[0] == -1.0 and s[-1] == 1.0
        assert abs(sum(s)) < 1e-9
        assert all(-1.0 <= v <= 1.0 for v in s)


def test_the_signal_is_monotonic_in_the_net():
    nets = [5, -3, 11, 0, -20]
    s = RF.relative_cohort_signals(nets)
    pairs = sorted(zip(nets, s))
    assert [v for _, v in pairs] == sorted(v for _, v in pairs)


# ------------------------------------------------------------------- ties
def test_ties_share_their_average_rank():
    assert RF.average_ranks([10, 20, 20, 40]) == [1.0, 2.5, 2.5, 4.0]
    assert RF.average_ranks([7, 7, 7]) == [2.0, 2.0, 2.0]


def test_tied_nets_get_the_identical_signal():
    s = RF.relative_cohort_signals([100, 50, 50, 10])
    assert s[1] == s[2]
    assert s[0] == 1.0 and s[-1] == -1.0


def test_a_wholly_tied_cohort_teaches_nothing_to_anyone():
    """Every member is the average rank, so every signal is exactly neutral."""
    s = RF.relative_cohort_signals([42, 42, 42, 42])
    assert s == [0.0, 0.0, 0.0, 0.0]
    assert all(RF.reinforcement_from_signal(v) == (0, 0.0) for v in s)


def test_ties_are_exact_on_integers_and_not_a_tolerance():
    wei = 10 ** 16
    assert RF.average_ranks([wei, wei + 1, wei]) == [1.5, 3.0, 1.5]


# ---------------------------------------------------------------- n_min
def test_a_cohort_below_n_min_produces_no_lesson_at_all():
    assert RF.relative_cohort_signals([1, 2]) is None
    assert RF.relative_cohort_signals([1]) is None
    assert RF.relative_cohort_signals([]) is None


def test_none_is_not_an_empty_list_and_not_a_list_of_zeros():
    """"teaches nothing" must not be confusable with "teaches neutrality"."""
    assert RF.relative_cohort_signals([1, 2]) is not []
    assert RF.relative_cohort_signals([1, 2]) is None
    assert RF.relative_cohort_signals([1, 2, 3]) == [-1.0, 0.0, 1.0]


def test_n_min_is_three_in_the_module_and_in_the_registered_file():
    assert RF.N_MIN == 3
    assert CONFIG["reinforcement"][RF.RELATIVE_COHORT_V1]["n_min"] == 3


# --------------------------------------------------- valence and amount
def test_the_sign_of_s_is_the_valence_and_its_magnitude_is_the_amount():
    assert RF.reinforcement_from_signal(1.0) == (1, 1.0)
    assert RF.reinforcement_from_signal(0.6) == (1, 0.6)
    assert RF.reinforcement_from_signal(-0.2) == (-1, 0.2)
    assert RF.reinforcement_from_signal(-1.0) == (-1, 1.0)


def test_a_neutral_signal_delivers_nothing():
    assert RF.reinforcement_from_signal(0.0) == (0, 0.0)
    assert RF.reinforcement_from_signal(-0.0) == (0, 0.0)


def test_the_amount_is_sign_symmetric():
    for value in (0.2, 0.6, 1.0):
        up = RF.reinforcement_from_signal(value)
        down = RF.reinforcement_from_signal(-value)
        assert up[1] == down[1]
        assert up[0] == -down[0]


def test_no_clipping_can_occur_and_no_cap_is_consulted():
    """|s| <= 1 by construction, so the cap is unreachable and unread."""
    for n in range(3, 40):
        s = RF.relative_cohort_signals(list(range(n)))
        assert max(abs(v) for v in s) == 1.0
    source = (ROOT / "flytrade" / "pons" / "reinforcement.py").read_text()
    body = source[source.index("def relative_cohort_signals"):
                  source.index("def reinforcement_for")]
    assert "REINFORCE_CAP" not in body
    assert "reinforce_full_scale" not in body


# ------------------------------------------------------------- selector
def test_a_configuration_with_no_rule_key_takes_the_absolute_path():
    assert RF.rule_from_config(None) == RF.ABSOLUTE_PROFIT_V1
    assert RF.rule_from_config({}) == RF.ABSOLUTE_PROFIT_V1
    assert RF.rule_from_config({"reinforcement": {}}) == RF.ABSOLUTE_PROFIT_V1


def test_every_d10_and_d11_configuration_selects_the_absolute_rule():
    for name in ("d10/config.json", "d11/config.json", "d11/d11_001.json"):
        cfg = json.loads((ROOT / "experiments" / name).read_text())
        assert RF.rule_from_config(cfg) == RF.ABSOLUTE_PROFIT_V1, name


def test_the_d12_configuration_selects_the_relative_rule():
    assert RF.rule_from_config(CONFIG) == RF.RELATIVE_COHORT_V1


def test_an_unknown_rule_raises_rather_than_falling_back():
    with pytest.raises(RF.UnknownRule):
        RF.rule_from_config({"reinforcement": {"rule": "profit_v9"}})


def test_the_absolute_branch_returns_exactly_what_the_execution_returns():
    """The dispatch must be a pass-through, or D5-D11 are not byte-identical."""
    class FakeExecution:
        def __init__(self):
            self.seen = []

        def reinforcement(self, outcome):
            self.seen.append(outcome)
            return (-1, 0.375)

    x = FakeExecution()
    sentinel = object()
    assert RF.reinforcement_for(RF.ABSOLUTE_PROFIT_V1, outcome=sentinel,
                                execution=x) == (-1, 0.375)
    assert x.seen == [sentinel]


def test_the_loop_refuses_the_relative_rule_rather_than_teaching_absolutely():
    """PonsLoop holds one position; it cannot form a cohort and must say so."""
    with pytest.raises(ValueError) as exc:
        LOOP.PonsLoop(driver=None, run=None, mb=None, credit=None,
                      journal=None, encoder=None, admission=None,
                      execution=None, policy=None, universe=None,
                      mode=LOOP.MODE_REPLAY, learning=LOOP.LEARN,
                      branch="x", run_id="x",
                      reinforcement_rule=RF.RELATIVE_COHORT_V1)
    assert "school" in str(exc.value)


def test_the_loops_default_rule_is_the_one_every_earlier_wave_took():
    import inspect
    sig = inspect.signature(LOOP.PonsLoop.__init__)
    assert sig.parameters["reinforcement_rule"].default == RF.ABSOLUTE_PROFIT_V1
