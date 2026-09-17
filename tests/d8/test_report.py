"""
`results.md` — amendment §10, and the language discipline the owner fixed.

The report is assembled by `experiments/d8/report.py` out of the committed JSON
artifacts, so these tests check two things: that it says what the amendment
requires, in the wording the amendment requires, and that its headline numbers
are the artifacts' numbers rather than a retelling.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import report as RP                                  # experiments/d8

ROOT = Path(__file__).resolve().parents[2]
D8 = ROOT / "experiments" / "d8"
MD = (D8 / "results.md").read_text()
SPEC = (ROOT / "docs" / "SPEC.md").read_text()
MODELS = json.loads((D8 / "models.json").read_text())
TABLE = json.loads((D8 / "features_pc1.json").read_text())
AUDIT = json.loads((D8 / "alignment.json").read_text())
GRIDS = json.loads((D8 / "grids.json").read_text())

#: §2's five statements, as the amendment writes them
BOUNDARIES = (
    "An untrained brain near AUC 0.5 does not establish that\n"
    "  its inputs contain no predictive information.",
    "Univariate AUCs near 0.5 do not exclude joint interactions\n"
    "  or non-monotonic relationships.",
    "PC1 maximizes represented variance, not predictiveness.\n"
    "  A nonpredictive PC1 does not establish a nonpredictive\n"
    "  complete sensory representation.",
    "Failure of the diagnostic models below is evidence about\n"
    "  these models, data and target, not a universal input ceiling.",
    "D7 measured fixed-90-minute context ranking, while actual\n"
    "  learning outcomes followed earlier neural exits.",
)


def sentences(text: str, needle: str):
    """Every sentence of ``text`` containing ``needle``."""
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if needle in s]


# ------------------------------------------------- the five boundaries

def test_the_five_boundaries_are_in_the_spec_where_the_report_reads_them():
    for b in BOUNDARIES:
        assert b in SPEC, b[:40]


def test_the_five_boundaries_appear_verbatim_at_the_head_of_the_conclusions():
    head = MD.index("## 7. Conclusions")
    tail = MD.index("### INPUT DIAGNOSTICS")
    block = MD[head:tail]
    for b in BOUNDARIES:
        assert b in block, b[:40]
    assert "Do not rewrite D7 as a success." in block


def test_the_extractor_returns_the_spec_bytes_and_nothing_of_its_own():
    got = RP.boundaries()
    assert got in SPEC
    assert got.startswith("2. CORRECT THE INFERENCE BOUNDARIES")
    for b in BOUNDARIES:
        assert b in got


# ----------------------------------------------------- the three sections

def test_the_three_conclusion_sections_are_separate_and_in_order():
    i = MD.index("### INPUT DIAGNOSTICS")
    j = MD.index("### TARGET ALIGNMENT")
    k = MD.index("### NEXT-STEP RECOMMENDATION")
    assert i < j < k


def test_option_c_is_not_launched():
    sec = MD[MD.index("### NEXT-STEP RECOMMENDATION"):]
    assert "Option (c) is not launched" in sec
    assert "not an authorisation" in sec
    assert "separate explicit policy amendment" in sec


def test_d7s_conclusion_b_is_preserved_and_not_rewritten():
    assert "B — suppression without demonstrated discrimination improvement" in MD
    assert "Nothing here rewrites it." in MD


# --------------------------------------------------- language discipline

def test_the_negative_is_stated_in_the_permitted_wording():
    assert "no detectable signal with these methods on these periods" in MD.lower()


def test_the_forbidden_universal_claim_is_only_ever_negated():
    hits = sentences(MD, "nothing can learn from these inputs")
    assert hits, "the phrase should appear, as the thing this wave does not say"
    for s in hits:
        assert "not" in s, s


def test_the_evaluation_dates_are_not_called_a_pristine_holdout():
    hits = sentences(MD, "pristine holdout")
    assert hits
    for s in hits:
        assert "not a pristine holdout" in s, s


def test_no_diagnostic_result_is_attributed_to_the_fly():
    lowered = MD.lower()
    for claim in ("the fly learned", "the fly detected", "the fly ranked",
                  "the fly ranks", "the fly discriminates", "the brain found",
                  "the fly found"):
        assert claim not in lowered, claim
    assert "never attributed to the fly" in MD


def test_no_claim_of_skill_alpha_or_profitability():
    lowered = MD.lower()
    for claim in ("profitable strategy", "edge over the market",
                  "tradable signal", "predicts returns", "beats the market"):
        assert claim not in lowered, claim
    # "alpha" may appear only inside the disclaimer that denies it
    for s in sentences(lowered, "alpha"):
        assert "no claim of skill, alpha or profitability" in s, s


def test_the_retrospective_label_and_the_prior_exposure_are_stated():
    assert "RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY OBSERVED" in MD
    assert "already observed" in MD
    assert "not an independent confirmation" in MD


def test_the_dependence_caveat_is_stated():
    assert "not independent examples" in MD
    assert "not simultaneous family-wise evidence" in MD
    assert "descriptive and conditional" in MD


def test_no_discovery_is_declared_by_picking_a_column():
    assert "every diagnostic is shown above" in MD
    assert "It is not the final input-informativeness verdict." in MD


# ----------------------------------------------- the numbers are the artifacts

def test_the_primary_model_is_named_and_its_number_is_the_artifact_s():
    prim = next(m for m in MODELS["models"] if m["primary"])
    assert prim["name"] == "NONLINEAR on X_SENSORY"
    assert f"**{prim['mean_auc']:.4f}**" in MD
    assert f"{prim['bootstrap']['p2.5']:.4f} … {prim['bootstrap']['p97.5']:.4f}" in MD


def test_every_model_row_appears_with_its_recorded_mean():
    for m in MODELS["models"]:
        assert f"| {m['name']} | {m['fitting']['in_sample_auc']:.4f} | " \
               f"**{m['mean_auc']:.4f}**" in MD


def test_every_column_of_the_feature_table_appears_with_its_recorded_means():
    for c in TABLE["columns"]:
        if c.get("degenerate"):
            continue
        assert f"| `{c['column']}` |" in MD
        assert f"{c['mean_auc_raw']:.4f} | {c['mean_auc_oriented']:.4f}" in MD


def test_the_alignment_headline_numbers_are_the_audit_s():
    s = AUDIT["summary"]
    assert f"**{s['exits_before_H']} of {s['episodes']}**" in MD
    assert f"**{s['sign_comparison']['proportion_disagreeing']:.4f}**" in MD
    assert f"{s['hypothetical_label_counts']['Y=1']} profitable / " \
           f"{s['hypothetical_label_counts']['Y=0']} not" in MD


def test_the_provenance_table_shows_before_and_after_and_they_agree():
    assert "sha256 before | sha256 after" in MD
    assert "All eleven unchanged: **True**." in MD
    assert MD.count("| **yes** |") == 11
    assert "**NO**" not in MD


def test_the_reconstruction_stop_condition_is_reported_as_zero():
    assert GRIDS["mismatches_total"] == 0
    assert "**0 mismatches on 5,579 rows**" in MD


def test_the_sklearn_version_and_thread_pin_are_recorded():
    assert f"scikit-learn {MODELS['sklearn']}" in MD
    assert "`OMP_NUM_THREADS=1`" in MD


def test_the_vacuous_sequence_clause_and_the_discontinuity_are_named():
    assert "The encoder delivers no sequence." in MD
    assert "satisfied vacuously" in MD
    assert "−22 % overnight discontinuity" in MD
    assert "2026-07-13 and 2026-07-14" in MD


def test_no_matched_participation_table_is_present():
    assert "**No matched-participation table.**" in MD
    assert "matched_participation` is not\ncalled by D8" in MD or \
        "matched_participation` is not called by D8" in MD
