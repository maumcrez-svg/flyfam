"""``pons_encoder_v2``: no manufactured diversity, and a schema a brain cannot
silently outgrow.

Owner bullets 12 and 16. The annotations, the glomerular channel rule and the
drive arithmetic are the repository's own; only the market numbers are scripted.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flytrade import encoder as E
from flytrade import populations as POP
from flytrade.pons import encoder as E1
from flytrade.pons import encoder_v2 as E2
from flytrade.pons.context_v2 import PONS_FEATURES_V2, context_v2
from tests.d11 import fixtures as F

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "experiments" / "d11" / "config.json").read_text())
SCALES = CONFIG["features"]["scales"]


@pytest.fixture(scope="module")
def ann():
    return POP.Annotations.load(ROOT / "data" / "malecns-v1.0" / "annotations.npz")


@pytest.fixture(scope="module")
def encoder(ann):
    return E2.SensoryEncoderV2(ann, SCALES)


# ------------------------------------------------------- the declared shape
def test_ten_features_take_twenty_channels(encoder):
    assert encoder.version == "pons_encoder_v2"
    assert list(encoder.features) == list(PONS_FEATURES_V2)
    assert encoder.dropped == ()
    assert len(encoder.olfactory.channels) == 10
    assert len(encoder.olfactory.glomeruli) == 20


def test_v1_is_untouched(ann):
    v1 = E1.SensoryEncoder(ann, CONFIG["features"]["scales"] |
                           json.loads((ROOT / "experiments" / "d10"
                                       / "config.json").read_text())
                           ["features"]["scales"],
                           features=tuple(json.loads(
                               (ROOT / "experiments" / "d10"
                                / "config.json").read_text())
                               ["features"]["order"]))
    assert v1.version == "pons_encoder_v1"
    assert len(v1.olfactory.glomeruli) == 16


def test_the_channel_map_matches_the_registered_one(encoder):
    assert encoder.channels == CONFIG["encoder"]["channel_map"]


def test_the_pathway_constants_are_the_verified_ones(encoder):
    assert encoder.olfactory.carrier == CONFIG["encoder"]["carrier"]
    assert encoder.olfactory.drive_budget_hz == CONFIG["encoder"]["drive_budget_hz"]
    assert encoder.olfactory.drive_max_hz == CONFIG["encoder"]["drive_max_hz"]
    assert encoder.olfactory.coding == CONFIG["encoder"]["coding"]


# ------------------------------------ bullet 12: no manufactured diversity
def test_two_tokens_with_equal_raw_vectors_produce_equal_rate_vectors(encoder):
    """Identical measured contexts are ALLOWED to encode identically."""
    one = F.traded_at((20, 250, 290), token="0x" + "a" * 40,
                      curve="0x" + "b" * 40)
    two = F.traded_at((20, 250, 290), token="0x" + "c" * 40,
                      curve="0x" + "d" * 40)
    cutoff = F.FIRST_TS + 300
    a = context_v2(one, cutoff, stable_id=1)
    b = context_v2(two, cutoff, stable_id=997)
    assert a.raw == b.raw
    ra = encoder.olfactory.rates(a.normalized(encoder.scales, encoder.features))
    rb = encoder.olfactory.rates(b.normalized(encoder.scales, encoder.features))
    assert ra.keys() == rb.keys()
    for glom in ra:
        assert ra[glom] == rb[glom], "the address must not enter the stimulus"


def test_the_encoder_is_deterministic(encoder):
    tape = F.traded_at((20, 250, 290))
    ctx = context_v2(tape, F.FIRST_TS + 300)
    u = ctx.normalized(encoder.scales, encoder.features)
    first = encoder.olfactory.rates(u)
    for _ in range(5):
        assert encoder.olfactory.rates(u) == first


def test_a_different_measurement_produces_a_different_stimulus(encoder):
    cutoff = F.FIRST_TS + 300
    busy = context_v2(F.flat_but_busy_tape(), cutoff)
    dead = context_v2(F.quiet_tape(), cutoff)
    a = encoder.olfactory.rates(busy.normalized(encoder.scales, encoder.features))
    b = encoder.olfactory.rates(dead.normalized(encoder.scales, encoder.features))
    assert max(abs(a[g] - b[g]) for g in a) > 1.0


def test_an_unusable_observation_is_not_encoded_at_all(encoder):
    young = context_v2(F.traded_at((5, 10)), F.FIRST_TS + 30)
    with pytest.raises(E1.UnusableObservation):
        encoder.encode(young, symbol=young.token)


# ---------------------------------------- the schema hash and its rule
def test_the_schema_hash_is_the_registered_one(encoder):
    assert encoder.input_schema_sha256 == CONFIG["encoder"]["input_schema_sha256"]


def test_the_schema_hash_covers_the_features_the_scales_and_the_channels(ann):
    base = E2.SensoryEncoderV2(ann, SCALES)
    moved = dict(SCALES)
    moved["gross_volume_2m"] = float(SCALES["gross_volume_2m"]) * 2
    other = E2.SensoryEncoderV2(ann, moved)
    assert base.input_schema_sha256 != other.input_schema_sha256
    assert E2.schema_sha256(base.features, base.scales, base.channels) \
        == base.input_schema_sha256


def test_the_order_of_the_features_is_part_of_the_schema(ann):
    base = E2.SensoryEncoderV2(ann, SCALES)
    swapped = ("since_last_trade", "age") + tuple(PONS_FEATURES_V2[2:])
    other = E2.SensoryEncoderV2(ann, SCALES, features=swapped)
    assert base.input_schema_sha256 != other.input_schema_sha256


def test_the_schema_metadata_names_both_fields(encoder):
    meta = encoder.schema_metadata()
    assert meta["encoder_version"] == "pons_encoder_v2"
    assert meta["input_schema_sha256"] == encoder.input_schema_sha256


# --------------------- bullet 16: incompatible checkpoint metadata rejected
def test_a_matching_schema_is_accepted(encoder):
    assert E2.check_checkpoint_schema(
        encoder.schema_metadata(),
        input_schema_sha256=encoder.input_schema_sha256) == "match"


def test_a_different_schema_hash_is_refused(encoder):
    with pytest.raises(E2.SchemaMismatch):
        E2.check_checkpoint_schema(
            {"encoder_version": "pons_encoder_v2",
             "input_schema_sha256": "0" * 64},
            input_schema_sha256=encoder.input_schema_sha256)


def test_a_different_schema_hash_is_refused_even_from_the_clean_reference(encoder):
    with pytest.raises(E2.SchemaMismatch):
        E2.check_checkpoint_schema(
            {"input_schema_sha256": "0" * 64},
            input_schema_sha256=encoder.input_schema_sha256,
            from_clean_reference=True, checkpoint_digest="ba95",
            clean_reference_digest="ba95")


def test_a_missing_schema_is_refused_unless_it_is_the_clean_reference(encoder):
    digest = CONFIG["next_run"]["clean_reference_checkpoint"]["state_digest"]
    with pytest.raises(E2.SchemaMismatch):
        E2.check_checkpoint_schema(
            {}, input_schema_sha256=encoder.input_schema_sha256)
    with pytest.raises(E2.SchemaMismatch):
        E2.check_checkpoint_schema(
            {}, input_schema_sha256=encoder.input_schema_sha256,
            from_clean_reference=False, checkpoint_digest=digest,
            clean_reference_digest=digest)
    with pytest.raises(E2.SchemaMismatch):
        E2.check_checkpoint_schema(
            {}, input_schema_sha256=encoder.input_schema_sha256,
            from_clean_reference=True, checkpoint_digest="9" * 64,
            clean_reference_digest=digest)
    assert E2.check_checkpoint_schema(
        {}, input_schema_sha256=encoder.input_schema_sha256,
        from_clean_reference=True, checkpoint_digest=digest,
        clean_reference_digest=digest) == "clean_reference_exemption"


def test_a_name_that_disagrees_with_the_hash_is_refused(encoder):
    with pytest.raises(E2.SchemaMismatch):
        E2.check_checkpoint_schema(
            {"encoder_version": "pons_encoder_v1",
             "input_schema_sha256": encoder.input_schema_sha256},
            input_schema_sha256=encoder.input_schema_sha256)


# ------------------------------- the journal carries and enforces the schema
def test_the_journal_writes_the_schema_into_the_checkpoint_and_checks_it_back(
        tmp_path, ann):
    import flytrade.records as REC
    from tests.d10.test_loop import _FakeCredit, _FakeMB

    encoder = E2.SensoryEncoderV2(ann, SCALES)
    mb = _FakeMB()
    versions = REC.Versions(market="pons_context_v2", encoder=encoder.version,
                            runner="r", decoder="d", execution="x",
                            mushroom="m", graph_sha256="0" * 64)
    journal = REC.Journal(tmp_path / "b", mb=mb, credit=_FakeCredit(mb),
                          versions=versions)
    journal.schema_meta = encoder.schema_metadata()
    journal.save_checkpoint(last_settled_episode=-1)
    loaded = journal.load_checkpoint_into_brain()
    assert loaded is not None
    assert loaded["events"]["input_schema_sha256"] == encoder.input_schema_sha256

    journal.schema_meta = {"encoder_version": "pons_encoder_v2",
                           "input_schema_sha256": "f" * 64}
    with pytest.raises(E2.SchemaMismatch):
        journal.load_checkpoint_into_brain()


def test_a_journal_without_a_schema_checks_nothing(tmp_path):
    """Every wave before D11 loads exactly as it always did."""
    import flytrade.records as REC
    from tests.d10.test_loop import _FakeCredit, _FakeMB

    mb = _FakeMB()
    versions = REC.Versions(market="pons_context_v1", encoder="pons_encoder_v1",
                            runner="r", decoder="d", execution="x",
                            mushroom="m", graph_sha256="0" * 64)
    journal = REC.Journal(tmp_path / "b", mb=mb, credit=_FakeCredit(mb),
                          versions=versions)
    assert journal.schema_meta == {}
    journal.save_checkpoint(last_settled_episode=-1)
    loaded = journal.load_checkpoint_into_brain()
    assert loaded is not None
    assert "input_schema_sha256" not in loaded["events"]
    assert journal.check_schema(loaded) is None
