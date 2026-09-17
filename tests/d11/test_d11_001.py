"""D11-001: the registered run configuration, and the rules that carry numbers.

Mapped to the owner's sections of the D11-001 spec:

===================================== =========================================
owner section                         test
===================================== =========================================
DATA                                  ``test_the_window_is_twelve_hours_and_does_not_touch_d10``,
                                      ``test_initial_states_are_present_and_the_store_matches_its_manifest``
                                      (split rule) ``test_the_split_is_seventy_thirty_on_the_anchored_grid``,
                                      ``test_every_episode_settles_inside_its_own_partition``
LEARNING                              ``test_the_applied_reinforce_scale_is_the_registered_one``,
                                      ``test_the_d10_configuration_still_applies_one_hundredth``,
                                      ``test_the_entry_deadline_refuses_a_buy_at_the_boundary``
FROZEN                                ``test_the_replicate_seeds_are_not_keyed_to_the_learned_state``
GRID                                  ``test_the_grid_takes_every_eligible_candidate_and_caps_nothing``
PRIMARY                               ``tests/d11/test_stats.py`` (known answers)
SUPPRESSION                           ``tests/d11/test_stats.py::test_the_class_contrast_*``
REINFORCEMENT                         ``test_a_learning_record_carries_the_raw_net_and_the_clipped_flag``
CONTEXT                               ``tests/d11/test_admission_v2.py``, ``test_context_v2.py``
INCONCLUSIVE                          ``test_the_inconclusive_conditions_are_registered_verbatim``
AFTER REPLAY                          ``test_the_live_hour_is_declared_after_the_report_and_keeps_learning``
DELIVERY                              ``test_the_registration_precedes_every_number``,
                                      ``tests/d11/test_hygiene.py``
===================================== =========================================
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

from flytrade import readout as RO                        # noqa: E402
from flytrade.pons import paper as PAPER                  # noqa: E402

CFG_V2 = json.loads((D11 / "config.json").read_text())
CFG_RUN = json.loads((D11 / "d11_001.json").read_text())
CFG_D10 = json.loads((D10 / "config.json").read_text())


# ------------------------------------------------------------------ LEARNING
def test_the_applied_reinforce_scale_is_the_registered_one():
    """Not the number in the file: the number the executor actually divides by."""
    assert PAPER.reinforce_full_scale_from_config(CFG_V2) == 0.131032424
    x = PAPER.PonsPaperExecution(
        reinforce_full_scale=PAPER.reinforce_full_scale_from_config(CFG_V2))
    assert x.reinforce_full_scale == 0.131032424
    assert x.as_dict()["reinforce_full_scale"] == 0.131032424


def test_the_d10_configuration_still_applies_one_hundredth():
    """The D11 scale is per-experiment; D10's path is untouched."""
    assert PAPER.reinforce_full_scale_from_config(CFG_D10) == 0.01
    from flytrade import execution as X
    assert X.REINFORCE_FULL_SCALE == 0.01


def test_the_scale_changes_the_amount_and_nothing_else_about_the_rule():
    """Same sign, same cap, same normalisation; one parameter moved."""
    from flytrade import execution as X

    class Outcome:
        return_on_notional = -0.0655   # D10's q, the 90th percentile magnitude

    old = PAPER.PonsPaperExecution(reinforce_full_scale=0.01)
    new = PAPER.PonsPaperExecution(reinforce_full_scale=0.131032424)
    v_old, a_old = X.ExecutionPolicy.reinforcement(old, Outcome())
    v_new, a_new = X.ExecutionPolicy.reinforcement(new, Outcome())
    assert v_old == v_new == -1
    assert a_old == 1.0                    # clipped at the cap under 0.01
    assert 0.0 < a_new < 1.0               # and no longer clipped under 0.131
    assert old.reinforce_cap == new.reinforce_cap == 1.0


# -------------------------------------------------------------------- FROZEN
def test_the_replicate_seeds_are_not_keyed_to_the_learned_state():
    """The two branches must draw the same Poisson stream for the same row."""
    assert CFG_D10["readout"]["keyed_to_learned_state"] is False
    assert CFG_RUN["fixed_for_the_whole_wave"]["keyed_to_learned_state"] is False
    policy = RO.policy_comparison()
    assert policy.as_dict()["keyed_to_learned_state"] is False
    a = policy.seeds("a" * 64, "obs", 7)
    b = policy.seeds("b" * 64, "obs", 7)
    assert a == b, "the seed schedule moved with the weights"
    assert policy.seeds("a" * 64, "obs", 8) != a, "the stable id must matter"


def test_the_comparison_seed_tuple_is_observation_stable_id_replicate():
    assert RO.comparison_seed("obs", 1, 0) != RO.comparison_seed("obs", 1, 1)
    assert RO.comparison_seed("obs", 1, 0) != RO.comparison_seed("obs", 2, 0)
    assert RO.comparison_seed("obs", 1, 0) == RO.comparison_seed("obs", 1, 0)


# ---------------------------------------------------------------------- split
def test_the_split_is_seventy_thirty_on_the_anchored_grid():
    import common as C
    window = {"first_ts": 1_000_000, "last_ts": 1_000_000 + 43_200}
    sp = C.split(window)
    assert sp["T"] == 1_000_000 + 30_240
    assert (sp["T"] - sp["t0"]) % 30 == 0
    assert sp["learning_share"] == pytest.approx(0.7, abs=30 / 43_200)


def test_the_split_floor_is_rational_and_not_a_float_artifact():
    """``0.7 * 43200`` is 30239.999999999996 in float64; the rule is exact."""
    import common as C
    for span in (43_200, 8_149, 3_600, 10_000, 99_991):
        sp = C.split({"first_ts": 0, "last_ts": span})
        assert sp["T"] == ((7 * span) // 10 // 30) * 30
    assert sp["learning_first_tick"] == sp["t0"]
    assert sp["learning_last_tick"] == sp["T"]
    assert sp["frozen_first_tick"] >= sp["T"]
    assert sp["frozen_last_tick"] + 902 <= sp["t1"]
    assert sum(b["ticks"] for b in sp["temporal_blocks"]) == sp["frozen_ticks"]
    assert len(sp["temporal_blocks"]) == 3


def test_every_episode_settles_inside_its_own_partition():
    import common as C
    sp = C.split({"first_ts": 1_000_000, "last_ts": 1_000_000 + 43_200})
    assert sp["learning_last_entry_tick"] + 902 <= sp["T"]
    assert sp["learning_last_entry_tick"] + 902 + 30 > sp["T"]
    for cutoff in range(sp["frozen_first_tick"], sp["frozen_last_tick"] + 1, 30):
        assert cutoff + 902 <= sp["t1"]


def test_the_geometric_ceiling_counts_non_overlapping_slots():
    import common as C
    out = C.geometric_ceiling(1_000_000, 1_000_000 + 902 + 932 * 4)
    assert out["ceiling"] == 5           # the first slot plus four more
    assert C.geometric_ceiling(None, 1_000_000)["ceiling"] == 0
    assert C.geometric_ceiling(1_000_000, 1_000_100)["ceiling"] == 0


# ------------------------------------------------------------ entry deadline
def test_the_entry_deadline_refuses_a_buy_at_the_boundary():
    """A decoded BUY whose settlement would cross ``T`` is recorded, not placed."""
    from flytrade.pons import loop as LOOP

    class Fake:
        latency_s, horizon_s = 2, 900

    loop = LOOP.PonsLoop.__new__(LOOP.PonsLoop)
    loop.x = Fake()
    loop.entry_deadline_ts = 10_000
    assert loop.beyond_entry_deadline(10_000 - 902) is False
    assert loop.beyond_entry_deadline(10_000 - 901) is True
    assert loop.beyond_entry_deadline(10_000) is True
    loop.entry_deadline_ts = None
    assert loop.beyond_entry_deadline(10 ** 12) is False


def test_the_d10_configuration_declares_no_entry_deadline():
    """Nothing about the D10 path moved: no deadline is the default."""
    from flytrade.pons import loop as LOOP
    import inspect
    sig = inspect.signature(LOOP.PonsLoop.__init__)
    assert sig.parameters["entry_deadline_ts"].default is None


# --------------------------------------------------------------- REINFORCEMENT
def test_a_learning_record_carries_the_raw_net_and_the_clipped_flag():
    """``Journal.settle``'s additive ``extra``, and it cannot shadow the event."""
    from flytrade import records as REC
    import inspect
    assert "extra" in inspect.signature(REC.Journal.settle).parameters
    assert inspect.signature(REC.Journal.settle).parameters["extra"].default is None
    source = inspect.getsource(REC.Journal.settle)
    # the extra is written UNDER the event's own fields
    assert "**(extra or {}),\n                      **ev.as_dict()" in source


# --------------------------------------------------------------- INCONCLUSIVE
def test_the_inconclusive_conditions_are_registered_verbatim():
    owner = [
        "fewer than 20 completed LEARNING episodes",
        "fewer than 100 paired FROZEN candidate labels",
        "either positive or negative outcome class has fewer than 20 "
        "labeled examples",
        "paired neural coverage below 95%",
        "material encoder saturation or invalid-state rate above 5%",
    ]
    assert CFG_RUN["inconclusive_conditions"]["verbatim_from_the_owner"] == owner
    assert "not loosened" in CFG_RUN["inconclusive_conditions"]["do_not_loosen"]


def test_the_statistics_plan_is_fixed_before_the_run():
    plan = CFG_RUN["statistics"]
    assert plan["uncertainty"]["resamples"] == 10_000
    assert plan["uncertainty"]["seed"] == 20_260_913
    assert plan["uncertainty"]["method"].startswith("paired cluster bootstrap")
    assert "stable_id" in plan["uncertainty"]["method"]
    assert "ties counted one half" in plan["auc"]
    for banned in ("significant", "proves"):
        assert f"Never '{banned}'" in plan["wording_rule"] or \
               f"never '{banned}'" in plan["wording_rule"] or \
               banned in plan["wording_rule"]


# ------------------------------------------------------------------ AFTER
def test_the_live_hour_is_declared_after_the_report_and_keeps_learning():
    live = CFG_RUN["live_hour"]
    assert live["when"].startswith("only after the replay report")
    assert live["learning"].startswith("LEARN")
    assert live["seconds"] == 3600
    assert "not started" in live["if_not_fresh_at_start"].lower()
    assert live["no_real_money"].startswith("paper only")


# ------------------------------------------------------------------ DELIVERY
def test_the_registration_precedes_every_number():
    """Step (ii) carries rules; step (iii) carries numbers and nothing chosen."""
    assert CFG_RUN["registration"]["step"] == "(ii)"
    assert "before any request to any node" in CFG_RUN["registration"]["rule"]
    step_iii = D11 / "split.json"
    if step_iii.exists():
        data = json.loads(step_iii.read_text())
        assert data["step"].startswith("(iii)")
        assert "No neural number exists yet" in data["rule"]


def test_the_fixed_parameters_are_the_ones_the_owner_named():
    fixed = CFG_RUN["fixed_for_the_whole_wave"]
    assert fixed["max_open_positions"] == 1
    assert fixed["horizon_seconds"] == 900
    assert fixed["cadence_seconds"] == 30
    assert fixed["max_candidates_per_round"] == 6
    assert fixed["readout_k"] == 8
    assert fixed["reinforce_full_scale"] == 0.131032424
    assert fixed["admission"] == "admission_v2"
    assert fixed["context"] == "pons_context_v2"
    assert fixed["encoder"] == "pons_encoder_v2"
    assert fixed["from_clean_reference"] is True


def test_the_grid_takes_every_eligible_candidate_and_caps_nothing():
    grid = CFG_RUN["grid"]
    assert "no cap of 6" in grid["construction"][1]
    assert "no rotation" in grid["construction"][1]
    assert grid["read_only"].startswith("both frozen brains are loaded read-only")
    assert "identical across branches by construction" in grid["rows"]


def test_the_label_declares_what_it_never_does():
    label = CFG_RUN["label"]
    assert set(label["it_never"]) == {
        "creates a trade", "alters bankroll", "produces reinforcement",
        "touches the ledger or a checkpoint"}
    assert "to the wei" in label["known_answer_test_written_before_the_grid_runs"]


# ---------------------------------------------------------------------- DATA
@pytest.mark.skipif(not (ROOT / "data/pons/d11-backfill-v1/MANIFEST.json").exists(),
                    reason="the collected store is gitignored")
def test_the_window_is_twelve_hours_and_does_not_touch_d10():
    man = json.loads(
        (ROOT / "data/pons/d11-backfill-v1/MANIFEST.json").read_text())
    window = man["window"]
    assert window["seconds"] == 43_200
    assert window["admission_minutes"] == 705
    assert window["settlement_tail_minutes"] == 15
    assert window["overlaps_d10_backfill_v1"] is False
    d10 = window["d10_backfill_v1"]
    assert window["first_block"] > d10["last_block"]
    assert window["first_ts"] > d10["last_ts"]
    assert man["endpoint"]["class"] == "loopback"
    assert man["endpoint"]["remote_requests"] == 0
    assert man["initial_states"]["from_eth_call"] == 0


@pytest.mark.skipif(not (ROOT / "data/pons/d11-backfill-v1/MANIFEST.json").exists(),
                    reason="the collected store is gitignored")
def test_initial_states_are_present_and_the_store_matches_its_manifest():
    import hashlib
    store = ROOT / "data/pons/d11-backfill-v1"
    man = json.loads((store / "MANIFEST.json").read_text())
    assert (store / "initial_states.json").exists()
    states = json.loads((store / "initial_states.json").read_text())
    assert len(states) > 0
    for name, entry in man["files"].items():
        path = store / name
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == entry["sha256"], name
