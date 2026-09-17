"""The two grids, the pre-registered wording, and the six conditions.

The token-disjoint primary filter, the three readings of addendum 7 and the
learning-curve summary are all pure functions here; the same assertions on the
real run's numbers are in ``test_artifacts.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import analyse as EV
import stats as ST

ROOT = Path(__file__).resolve().parents[2]
D12 = ROOT / "experiments" / "d12"
CONFIG = json.loads((D12 / "d12_001.json").read_text())


# ------------------------------------------------- the token-disjoint grid
def rows(tokens):
    return [{"token": t, "stable_id": i} for i, t in enumerate(tokens)]


def test_the_primary_grid_drops_every_row_of_a_token_that_was_a_lesson():
    out = EV.primary_rows(rows(["a", "b", "c", "b"]), {"b"})
    assert [r["token"] for r in out] == ["a", "c"]


def test_the_primary_grid_is_disjoint_from_the_lesson_tokens_by_address():
    lessons = {"0xaa", "0xbb"}
    out = EV.primary_rows(rows(["0xaa", "0xcc", "0xbb", "0xdd"]), lessons)
    assert {r["token"] for r in out}.isdisjoint(lessons)


def test_an_empty_lesson_set_leaves_every_row_and_a_full_one_leaves_none():
    every = rows(["a", "b", "c"])
    assert len(EV.primary_rows(every, set())) == 3
    assert EV.primary_rows(every, {"a", "b", "c"}) == []


def test_the_filter_is_by_address_and_not_by_stable_id():
    """The two grids were built by different passes; a stable id means nothing."""
    out = EV.primary_rows([{"token": "a", "stable_id": 1},
                           {"token": "b", "stable_id": 1}], {"a"})
    assert [r["token"] for r in out] == ["b"]


def test_the_registration_defines_the_primary_grid_as_never_a_lesson():
    assert "never" in CONFIG["grids"]["primary"]["definition"].lower()
    assert CONFIG["grids"]["secondary"][
        "reported_regardless_of_the_verdict"] is True


# ------------------------------------------------ the pre-registered wording
def test_an_interval_entirely_above_zero_reads_as_the_registered_sentence():
    reading = EV.preregistered_reading({"lo": 0.01, "hi": 0.2})
    assert reading == CONFIG["statistics"]["preregistered_readings"][
        "entirely_above_zero"]
    assert "not compatible with sampling variation" in reading


def test_an_interval_including_zero_reads_as_compatible_with_variation():
    for interval in ({"lo": -0.1, "hi": 0.1}, {"lo": 0.0, "hi": 0.2},
                     {"lo": -0.2, "hi": 0.0}):
        assert EV.preregistered_reading(interval) == "compatible with sampling variation"


def test_an_interval_entirely_below_zero_reads_as_the_inversion_persisting():
    assert EV.preregistered_reading({"lo": -0.22, "hi": -0.12}) == (
        "the inversion persists")


def test_no_reading_ever_says_significant_or_proves():
    for interval in ({"lo": 0.1, "hi": 0.2}, {"lo": -0.1, "hi": 0.1},
                     {"lo": -0.2, "hi": -0.1}, {"lo": None, "hi": None}):
        text = EV.preregistered_reading(interval).lower()
        assert "significant" not in text and "prove" not in text


def test_a_degenerate_interval_gets_no_reading_rather_than_a_default():
    assert "no reading applies" in EV.preregistered_reading(
        {"lo": None, "hi": None, "clusters": 0, "kept": 0})


def test_the_three_readings_are_the_ones_the_registered_file_carries():
    registered = CONFIG["statistics"]["preregistered_readings"]
    assert EV.preregistered_reading({"lo": 0.1, "hi": 0.2}) == registered[
        "entirely_above_zero"]
    assert EV.preregistered_reading({"lo": -0.1, "hi": 0.1}) == registered[
        "includes_zero"]
    assert EV.preregistered_reading({"lo": -0.2, "hi": -0.1}) == registered[
        "entirely_below_zero"]


# --------------------------------------------------------------- the AUCs
def test_delta_auc_of_two_identical_branches_is_exactly_zero():
    rows_ = [{"school": v, "reference": v, "y": bool(i % 2)}
             for i, v in enumerate([0.1, 0.9, 0.3, 0.7])]
    stat = ST.delta_auc_statistic("school", "reference", "y")
    assert stat(rows_) == 0.0


def test_auc_is_one_on_a_perfect_ranking_and_zero_on_its_reverse():
    y = [True, True, False, False]
    assert ST.auc([4, 3, 2, 1], y) == 1.0
    assert ST.auc([1, 2, 3, 4], y) == 0.0
    assert ST.auc([1, 1, 1, 1], y) == 0.5


def test_the_statistics_are_the_registered_ones():
    unc = CONFIG["statistics"]["uncertainty"]
    assert unc["resamples"] == ST.RESAMPLES == 10_000
    assert unc["seed"] == ST.SEED == 20_260_913
    assert "stable_id" in unc["method"]


# ------------------------------------------------------- the six conditions
def test_the_six_conditions_are_verbatim_from_the_registered_file():
    assert list(EV.CONDITIONS) == CONFIG["inconclusive_conditions"][
        "verbatim_from_addendum_9"]
    assert len(EV.CONDITIONS) == 6


def test_the_thresholds_named_in_the_conditions_are_the_registered_ones():
    text = " ".join(EV.CONDITIONS)
    for threshold in ("2,000", "100", "20", "95 %", "5 %", "25 %"):
        assert threshold in text


def test_the_wording_rule_forbids_the_two_words():
    rule = CONFIG["statistics"]["wording_rule"]
    assert "never 'significant'" in rule and "never 'proves'" in rule
