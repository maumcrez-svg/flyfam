"""The reinforcement scale: one parameter moves and nothing else does.

Owner bullets 13, 14 and 15, plus the wave's own requirement that the IBM
reinforcement path is byte-identical to what it was. The execution policy, the
credit assigner and the outcome records are the repository's own; the outcomes
are constructed so a test can ask for a neutral one and an extreme one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flytrade import execution as X
from flytrade.pons import paper as PAPER

ROOT = Path(__file__).resolve().parents[2]
D11 = json.loads((ROOT / "experiments" / "d11" / "config.json").read_text())
D10 = json.loads((ROOT / "experiments" / "d10" / "config.json").read_text())
CALIBRATION = json.loads(
    (ROOT / "experiments" / "d11" / "reward_calibration.json").read_text())

NEW_SCALE = float(D11["reinforcement"]["new_full_scale"])
OLD_SCALE = 0.01


class Outcome:
    """The one field ``ExecutionPolicy.reinforcement`` reads."""

    def __init__(self, r: float):
        self.return_on_notional = float(r)


def policy(scale=OLD_SCALE) -> X.ExecutionPolicy:
    """The real policy on a feed it never touches: ``reinforcement`` reads none."""
    return X.ExecutionPolicy(None, reinforce_full_scale=scale)


# --------------- bullet 13: monotonic, sign-symmetric reward magnitudes
@pytest.mark.parametrize("scale", [OLD_SCALE, NEW_SCALE])
def test_the_amount_is_monotonic_in_the_magnitude_of_the_outcome(scale):
    pol = policy(scale)
    amounts = [pol.reinforcement(Outcome(-r))[1]
               for r in (0.0001, 0.001, 0.005, 0.01, 0.05)]
    assert amounts == sorted(amounts)
    assert amounts[0] < amounts[-1]


@pytest.mark.parametrize("scale", [OLD_SCALE, NEW_SCALE])
def test_the_amount_is_sign_symmetric(scale):
    pol = policy(scale)
    for r in (0.0001, 0.001, 0.02, 0.5):
        up_v, up_a = pol.reinforcement(Outcome(+r))
        down_v, down_a = pol.reinforcement(Outcome(-r))
        assert up_v == +1 and down_v == -1
        assert up_a == down_a, "the same scale for gains and losses"


def test_the_same_scale_serves_both_signs_and_nothing_is_subtracted():
    pol = policy(NEW_SCALE)
    assert pol.reinforcement(Outcome(0.02))[1] == pol.reinforcement(Outcome(-0.02))[1]
    # a loss never becomes a positive reinforcement
    assert pol.reinforcement(Outcome(-0.5))[0] == -1
    assert pol.reinforcement(Outcome(-1e-9))[0] == -1


# ----------------------------- bullet 14: neutral and extreme outcomes
@pytest.mark.parametrize("scale", [OLD_SCALE, NEW_SCALE])
def test_a_neutral_outcome_delivers_nothing(scale):
    assert policy(scale).reinforcement(Outcome(0.0)) == (0, 0.0)


@pytest.mark.parametrize("scale", [OLD_SCALE, NEW_SCALE])
def test_an_extreme_outcome_is_capped_and_never_exceeds_the_cap(scale):
    pol = policy(scale)
    for r in (1.0, 10.0, 1e6):
        valence, amount = pol.reinforcement(Outcome(-r))
        assert valence == -1
        assert amount == pytest.approx(X.REINFORCE_CAP)
        assert amount <= X.REINFORCE_CAP


def test_a_vanishing_outcome_keeps_its_sign_and_a_tiny_amount():
    valence, amount = policy(NEW_SCALE).reinforcement(Outcome(-1e-9))
    assert valence == -1 and 0.0 < amount < 1e-6


# ---------------------------------- the calibrated scale and what it fixes
def test_the_new_scale_is_the_registered_rule_applied_to_the_eight_outcomes():
    rows = CALIBRATION["outcomes"]
    assert len(rows) == 8 == CALIBRATION["n"]
    assert CALIBRATION["old_full_scale"] == OLD_SCALE
    assert CALIBRATION["new_full_scale"] == pytest.approx(
        max(OLD_SCALE, 2.0 * CALIBRATION["q"]))
    assert NEW_SCALE == CALIBRATION["new_full_scale"]


def test_the_calibration_reproduces_the_amounts_the_log_recorded():
    pol = policy(OLD_SCALE)
    for row in CALIBRATION["outcomes"]:
        _, amount = pol.reinforcement(
            Outcome(row["net_return_from_the_outcome_record"]))
        assert amount == pytest.approx(row["old_amount_recorded"], abs=1e-6)


def test_the_two_reconstructions_of_every_net_return_agree():
    for row in CALIBRATION["outcomes"]:
        assert row["net_return_from_the_leg_integers"] is not None
        assert row["agreement_abs_difference"] <= CALIBRATION["agreement_tolerance"]


def test_the_new_scale_unclips_seven_of_the_eight():
    assert CALIBRATION["clipped_under_the_old_scale"] == 7
    assert CALIBRATION["clipped_under_the_new_scale"] == 0
    pol = policy(NEW_SCALE)
    amounts = [pol.reinforcement(Outcome(r["net_return_from_the_outcome_record"]))[1]
               for r in CALIBRATION["outcomes"]]
    assert all(a < X.REINFORCE_CAP for a in amounts)
    assert len(set(round(a, 9) for a in amounts)) > 1, \
        "different sizes must now deliver different amounts"


def test_the_calibration_set_excludes_the_duplicates_and_the_unsettled():
    ids = {row["episode_id"] for row in CALIBRATION["outcomes"]}
    assert 72000315 not in ids, "the pending live position"
    assert all(row["branch"] != "frozen_reference"
               for row in CALIBRATION["outcomes"])
    assert "the_determinism_rerun_of_d10-001_learning" in CALIBRATION["excluded"]


# ---------------------------- the parameter is per-experiment, not global
def test_the_repository_default_does_not_move():
    assert X.REINFORCE_FULL_SCALE == 0.01
    assert X.REINFORCE_CAP == 1.0
    assert X.ExecutionPolicy(None).reinforce_full_scale == 0.01
    assert PAPER.PonsPaperExecution().reinforce_full_scale == 0.01


def test_the_scale_is_read_from_the_experiment_config():
    assert PAPER.reinforce_full_scale_from_config(D11) == NEW_SCALE
    assert PAPER.reinforce_full_scale_from_config(D10) == 0.01
    assert PAPER.reinforce_full_scale_from_config(None) == 0.01
    assert PAPER.reinforce_full_scale_from_config({}) == 0.01
    assert PAPER.reinforce_full_scale_from_config(
        {"reinforcement": {"reinforce_full_scale": 0.25}}) == 0.25


def test_a_non_positive_configured_scale_is_refused():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            PAPER.reinforce_full_scale_from_config(
                {"reinforcement": {"reinforce_full_scale": bad}})


def test_the_ibm_reinforcement_path_is_byte_identical():
    """The historical loop's mapping on a fixed outcome, unchanged.

    ``experiments/historical/run.py`` builds its ``ExecutionPolicy`` from its
    own config's ``reinforce_full_scale``. These are the numbers that path
    produced before D11 and must still produce.
    """
    ibm = X.ExecutionPolicy(None, reinforce_full_scale=0.01, reinforce_cap=1.0)
    expected = {
        0.0: (0, 0.0),
        0.001: (1, 0.1),
        -0.001: (-1, 0.1),
        0.005: (1, 0.5),
        -0.005: (-1, 0.5),
        0.01: (1, 1.0),
        -0.01: (-1, 1.0),
        0.25: (1, 1.0),
        -0.25: (-1, 1.0),
    }
    for r, want in expected.items():
        valence, amount = ibm.reinforcement(Outcome(r))
        assert valence == want[0]
        assert amount == pytest.approx(want[1])


def test_the_historical_config_still_declares_the_old_scale():
    for path in sorted((ROOT / "experiments" / "historical").glob("*.json")):
        cfg = json.loads(path.read_text())
        scale = (cfg.get("execution") or {}).get("reinforce_full_scale",
                                                 cfg.get("reinforce_full_scale"))
        if scale is not None:
            assert float(scale) == 0.01, f"{path.name} moved the IBM scale"


# ------------------------- bullet 15: one normalised event per outcome
def test_one_settled_outcome_produces_exactly_one_learning_event(tmp_path):
    from tests.d10.test_loop import build
    from tests.d10 import fixtures as FD

    loop = build(tmp_path, tapes={})
    tape = FD.traded_tape()
    loop.tapes = {tape.token: tape}
    loop.by_curve = {tape.curve: tape}
    loop.universe.register(tape.token)
    loop.run_branch()
    settled = len(loop.x.outcomes)
    assert settled >= 1
    assert len(loop.journal.settled) == settled, \
        "exactly one normalised update per settled outcome, and no other"
    assert len({e for e, _, _ in loop.journal.settled}) == settled, \
        "no episode is settled twice"


def test_a_mark_and_a_blocked_sell_teach_nothing(tmp_path):
    from tests.d10.test_loop import build
    from tests.d10 import fixtures as FD

    loop = build(tmp_path, tapes={})
    tape = FD.traded_tape()
    loop.tapes = {tape.token: tape}
    loop.by_curve = {tape.curve: tape}
    loop.universe.register(tape.token)
    loop.run_branch()
    assert loop.marks > 0
    assert len(loop.journal.settled) == len(loop.x.outcomes)
    assert loop.tally.after_execution.get("blocked_by_fixed_hold", 0) >= 0
