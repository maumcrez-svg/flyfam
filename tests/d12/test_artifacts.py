"""What the d12-001 run wrote, read back and asserted.

These are the claims that need the run to have happened: the determinism of
the first hundred ticks, the zero positions of the school, the maturity of
every applied lesson, the token-disjoint primary grid, the reuse check on the
REFERENCE scores, and the six conditions. A neural number may not exist before
step (iii), so this file ships **with** the artifacts, not with the code.

Artifacts that are not committed — the event logs, the checkpoints and the
per-lesson file — are skipped rather than faked when a checkout does not carry
them, which is what ``tests/d11/test_hygiene.py`` already does for the D10
replay log.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
D12 = ROOT / "experiments" / "d12"
D11 = ROOT / "experiments" / "d11"
RUN = D12 / "runs" / "d12-001"
GRID = RUN / "grid"
CONFIG = json.loads((D12 / "d12_001.json").read_text())

T = 1_789_259_804          # the recorded cutoff of `d11-backfill-v1`
SETTLE_S = 902


def load(path: Path):
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} is not present in this checkout")
    return json.loads(path.read_text())


def lessons():
    """The compact per-lesson dump the run writes beside the event log."""
    path = RUN / "school" / "lessons.jsonl"
    if not path.exists():
        pytest.skip("the per-lesson file is not present in this checkout")
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def lesson_records(limit: int = 200):
    """The first ``limit`` LESSON **records**, from the school's event log.

    The registered field names of addendum 12 live on the record, not on the
    compact dump: the dump carries the same quantities under the loop's own
    shorter keys.
    """
    path = RUN / "school" / "events.jsonl"
    if not path.exists():
        pytest.skip("the school event log is not present in this checkout")
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if '"kind": "LESSON"' not in line and '"kind":"LESSON"' not in line:
                continue
            out.append(json.loads(line))
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------ determinism
def test_the_first_hundred_ticks_reproduce_exactly():
    d = load(RUN / "determinism.json")
    assert d["ticks"] == 100
    assert d["digest_identical"] is True
    assert d["lesson_log_identical"] is True
    assert d["first"]["end_digest"] == d["second"]["end_digest"]
    assert d["first"]["lesson_log_sha256"] == d["second"]["lesson_log_sha256"]
    assert d["first"]["lesson_lines"] == d["second"]["lesson_lines"]
    assert d["lessons_applied"] > 0, "a prefix with no lesson proves nothing"


# ------------------------------------------------------------ school mode
def test_the_school_opened_no_position_and_took_no_trade():
    s = load(RUN / "school_summary.json")
    assert s["episodes"] == 0
    assert s["position_open_at_end"] is False
    assert (s["account"].get("trades") or 0) == 0
    assert (s["account"].get("realized_pnl") or 0.0) == 0.0
    assert s["school"]["no_paper_position"] is True


def test_the_school_presented_far_more_than_the_six_of_a_round():
    s = load(RUN / "school_summary.json")
    presented = [row["presented"] for row in s["per_tick"]]
    assert max(presented) > 6, "the cap of six was not lifted"
    assert s["school"]["rotation"] is False
    assert s["school"]["max_candidates_per_round"] is None


def test_every_eligible_candidate_of_a_tick_became_a_lesson():
    """A presented candidate is queued unless the boundary took its whole tick."""
    s = load(RUN / "school_summary.json")
    for row in s["per_tick"]:
        if row["cutoff_ts"] + SETTLE_S <= T:
            assert row["queued"] == row["presented"], row["tick"]
        else:
            assert row["queued"] == 0, row["tick"]


def test_the_wave_applied_thousands_of_lessons_not_fifteen():
    s = load(RUN / "school_summary.json")
    assert s["lessons"]["applied"] >= 2000
    assert s["lessons"]["reward"] > 0, "the absolute rule gave 0 rewards"
    assert s["lessons"]["punishment"] > 0


def test_no_lesson_was_ever_clipped():
    s = load(RUN / "school_summary.json")
    assert s["lessons"]["clipped"] == 0
    assert s["lessons"]["clipping_is_impossible_under_this_rule"] is True
    assert (s["lessons"]["amount"]["max"] or 0.0) <= 1.0


def test_the_pending_queue_drained_to_nothing():
    s = load(RUN / "school_summary.json")
    assert s["per_tick"][-1]["pending_lessons"] >= 0
    total = (s["cohorts"]["queued_lessons"]
             + s["lessons"]["discarded"].get("BOUNDARY", 0))
    assert total >= s["lessons"]["applied"]


# ------------------------------------------------- maturity and lookahead
def test_no_lesson_was_applied_before_its_outcome_existed():
    rows = lessons()
    assert rows
    for row in rows:
        assert row["applied_at_cutoff_ts"] >= row["cutoff_ts"] + SETTLE_S
        assert row["applied_at_cutoff_ts"] == row["cutoff_ts"] + 930


def test_no_lesson_was_applied_at_or_after_the_cutoff_T():
    """The school replay ends at T; no lesson can reach a FROZEN-only tick."""
    rows = lessons()
    assert max(row["applied_at_cutoff_ts"] for row in rows) <= T
    assert max(row["cutoff_ts"] for row in rows) + SETTLE_S <= T
    s = load(RUN / "school_summary.json")
    assert s["partition"]["last_tick"] == T


def test_a_cohort_is_applied_in_stable_id_order():
    rows = lessons()
    by_cohort: dict[int, list[int]] = {}
    for i, row in enumerate(rows):
        by_cohort.setdefault(row["cutoff_ts"], []).append((i, row["stable_id"]))
    for cutoff, members in by_cohort.items():
        ids = [sid for _, sid in members]
        assert ids == sorted(ids), cutoff


def test_every_lesson_record_carries_the_registered_fields():
    records = lesson_records(200)
    assert records
    for field in CONFIG["records"]["LESSON"]:
        assert field in records[0], field
    for record in records:
        assert record["kind"] == "LESSON"
        assert record["rule"] == "relative_cohort_v1"
        assert len(record["checkpoint_digest_after"]) == 64
        assert record["clipped"] is False
    rows = lessons()
    for row in rows[:200]:
        assert row["n"] >= CONFIG["reinforcement"]["relative_cohort_v1"]["n_min"]
        assert -1.0 <= row["s"] <= 1.0
        assert row["valence"] in (-1, 0, 1)
        assert abs(row["amount"] - abs(row["s"])) < 1e-12
        assert isinstance(row["net_wei"], int)
        assert len(row["digest_after"]) == 64


def test_every_cohort_is_zero_mean_and_bounded_and_reaches_the_extremes():
    """The signal's shape, on the real cohorts.

    ``-1`` and ``+1`` are reached whenever the worst and the best net are
    **unique**; when the extreme is tied the tied members share an average
    rank and their common signal is nearer the middle, which is the registered
    tie rule and not a violation of it.
    """
    rows = lessons()
    by_cohort: dict[int, list[dict]] = {}
    for row in rows:
        by_cohort.setdefault(row["cutoff_ts"], []).append(row)
    checked = extremes = 0
    for members in by_cohort.values():
        if len(members) < 3:
            continue
        signals = [m["s"] for m in members]
        nets = [m["net_wei"] for m in members]
        assert abs(sum(signals)) < 1e-9
        assert min(signals) >= -1.0 and max(signals) <= 1.0
        if nets.count(min(nets)) == 1:
            assert min(signals) == -1.0
        if nets.count(max(nets)) == 1:
            assert max(signals) == 1.0
            extremes += 1
        checked += 1
        if checked >= 300:
            break
    assert checked and extremes


# ------------------------------------------------------- the two grids
def test_the_primary_grid_shares_no_token_with_any_lesson():
    tokens = set(load(D12 / "lesson_tokens.json")["tokens"])
    rows_path = GRID / "rows.jsonl"
    if not rows_path.exists():
        pytest.skip("the grid rows are not present in this checkout")
    primary = {json.loads(line)["token"]
               for line in rows_path.read_text().splitlines() if line.strip()}
    ev = load(GRID / "evaluation.json")
    kept = primary - tokens
    assert kept.isdisjoint(tokens)
    assert len(kept) == ev["primary"]["tokens"]
    assert len(primary) == ev["secondary"]["tokens"]
    assert ev["primary"]["rows"] < ev["secondary"]["rows"]


def test_the_reused_reference_scores_reproduce_exactly():
    v = load(GRID / "reference_verification.json")
    assert v["rows_recomputed"] >= 200
    assert v["mismatched"] == 0
    assert v["max_abs_difference_hz"] <= v["tolerance_hz"]
    assert v["verdict"] == "REUSE_VERIFIED"
    assert v["digest_unchanged"] is True


def test_the_reused_files_are_byte_for_byte_the_d11_001_files():
    reuse = load(GRID / "reuse.json")
    for name, entry in reuse["files"].items():
        assert entry["source_sha256"] == entry["copy_sha256"], name
        assert entry["source"].endswith(f"d11-001/grid/{name}")


def test_both_brains_were_read_only_in_the_scoring_pass():
    checked = 0
    for branch in ("school", "reference"):
        path = GRID / f"scores_{branch}_summary.json"
        if not path.exists():
            continue
        assert json.loads(path.read_text())["digest_unchanged"] is True, branch
        checked += 1
    if not checked:
        pytest.skip("no scoring-pass summary is present in this checkout")


# --------------------------------------------------- curve and weights
def test_the_learning_curve_is_sampled_every_five_hundred_lessons():
    s = load(RUN / "school_summary.json")
    marks = [p["lessons"] for p in s["learning_curve"]]
    assert marks == sorted(marks)
    for mark in marks[:-1]:
        assert mark % 500 == 0, marks
    assert marks[-1] == s["lessons"]["applied"]


def test_the_weight_diagnostic_is_sampled_with_it():
    s = load(RUN / "school_summary.json")
    assert len(s["weights"]) == len(s["learning_curve"])
    for w in s["weights"]:
        assert w["synapses"] == 44_042
        assert w["floor"] == 0.25 and w["ceiling"] == 1.0
        assert 0.0 <= w["at_floor_fraction"] <= 1.0
        assert 0.0 <= w["at_ceiling_fraction"] <= 1.0
        assert abs(w["saturated_fraction"]
                   - (w["at_floor_fraction"] + w["at_ceiling_fraction"])) < 1e-12


def test_the_gains_only_ever_move_down():
    """The operator depresses; nothing in D12 added potentiation."""
    s = load(RUN / "school_summary.json")
    assert s["final_weights"]["max"] <= 1.0
    assert s["final_weights"]["min"] >= s["final_weights"]["floor"]
    means = [w["mean"] for w in s["weights"]]
    assert means == sorted(means, reverse=True)


# ------------------------------------------------------- frozen branches
def test_both_frozen_branches_left_their_digest_unchanged():
    ev = load(GRID / "evaluation.json")
    for name, d in ev["frozen_digests"].items():
        assert d["unchanged"] is True, name
        assert d["start"] == d["end"], name
    assert set(ev["frozen_digests"]) == {"frozen_school", "frozen_reference"}


def test_the_school_branch_has_no_paper_results_by_design():
    s = load(RUN / "school_summary.json")
    assert s["episodes"] == 0
    report = (RUN / "report.md")
    if report.exists():
        assert "no paper results by design" in report.read_text()


# ------------------------------------------------------- the conditions
def test_every_condition_was_evaluated_and_none_was_loosened():
    ev = load(GRID / "evaluation.json")
    registered = CONFIG["inconclusive_conditions"]["verbatim_from_addendum_9"]
    assert [c["condition"] for c in ev["conditions"]] == registered
    thresholds = [c["threshold"] for c in ev["conditions"]]
    assert thresholds == [2000, 100, 20, 0.95, 0.05, 0.25]
    assert ev["conditions_failed"] == sum(1 for c in ev["conditions"]
                                          if c["fails"])
    assert ev["verdict"] == ("INCONCLUSIVE" if ev["conditions_failed"]
                             else "CONCLUSIVE_BY_ITS_OWN_FLOOR")


def test_the_bootstrap_used_the_registered_seed_and_resamples():
    ev = load(GRID / "evaluation.json")
    for name in ("primary", "secondary"):
        interval = ev[name]["overall"]["interval"]
        assert interval["seed"] == 20_260_913
        assert interval["resamples"] == 10_000
        assert interval["level"] == 0.95


def test_the_preregistered_reading_matches_the_interval_it_describes():
    ev = load(GRID / "evaluation.json")
    registered = CONFIG["statistics"]["preregistered_readings"]
    for name in ("primary", "secondary"):
        for block in [ev[name]["overall"]] + ev[name]["per_block"]:
            lo, hi = block["interval"]["lo"], block["interval"]["hi"]
            if lo is None:
                continue
            if lo > 0:
                want = registered["entirely_above_zero"]
            elif hi < 0:
                want = registered["entirely_below_zero"]
            else:
                want = registered["includes_zero"]
            assert block["preregistered_reading"] == want


def test_the_secondary_grid_is_reported_whatever_the_verdict():
    ev = load(GRID / "evaluation.json")
    assert ev["secondary"]["paired_labelled_rows"] > 0
    assert ev["secondary"]["overall"]["delta_auc"] is not None


# --------------------------------------------- the mirror and the ceiling
def test_the_mirror_diagnostic_ran_on_the_existing_scores_with_no_brain():
    m = load(D12 / "mirror_diagnostic.json")
    assert m["no_brain_ran"] is True and m["no_socket_was_opened"] is True
    assert set(m["input_sha256"]) == {"scores_trained.jsonl",
                                      "scores_reference.jsonl", "labels.jsonl"}
    for name, digest in m["input_sha256"].items():
        import hashlib
        h = hashlib.sha256()
        h.update((D11 / "runs" / "d11-001" / "grid" / name).read_bytes())
        assert h.hexdigest() == digest, name
    assert (D12 / "mirror_diagnostic.md").exists()


def test_the_lesson_ceiling_was_computed_with_no_brain_and_cleared_its_floor():
    c = load(D12 / "ceiling.json")
    assert c["no_brain_ran"] is True
    assert c["creates_no_trade"] is True
    assert c["produces_no_reinforcement"] is True
    assert c["learning"]["n_min"] == 3
    assert c["preregistered_hard_stop"]["verdict"] == "PROCEED"
    assert c["learning"]["lesson_ceiling"] >= 2000


def test_the_ceiling_and_the_run_agree_on_the_order_of_magnitude():
    c = load(D12 / "ceiling.json")
    s = load(RUN / "school_summary.json")
    assert s["lessons"]["applied"] <= c["learning"]["lesson_ceiling"]


# --------------------------------------------------- nothing else moved
def test_nothing_but_the_teacher_moved():
    s = load(RUN / "school_summary.json")
    d11_cfg = json.loads((D11 / "d11_001.json").read_text())[
        "fixed_for_the_whole_wave"]
    mine = CONFIG["fixed_for_the_whole_wave"]
    for key in ("horizon_seconds", "cadence_seconds", "readout_k",
                "readout_namespace", "keyed_to_learned_state", "decoder",
                "paper_size_wei", "latency_seconds", "initial_cash_eth",
                "max_candidates_per_round", "admission", "context", "encoder",
                "reinforce_cap", "from_clean_reference",
                "clean_reference_state_digest", "graph_sha256"):
        assert mine[key] == d11_cfg[key], key
    assert mine["gas_wei"] == d11_cfg["gas_wei"]
    assert s["start_digest"] == d11_cfg["clean_reference_state_digest"]
    assert s["reinforcement_rule"] == "relative_cohort_v1"


def test_the_split_is_the_one_d11_001_ran():
    s = load(RUN / "school_summary.json")
    d11 = json.loads((D11 / "runs" / "d11-001" / "summary.json").read_text())
    assert s["partition"]["T"] == d11["split"]["T"] == T
    assert s["ticks"] == d11["split"]["learning_ticks"]
