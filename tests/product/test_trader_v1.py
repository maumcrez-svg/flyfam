"""``brains/trader-v1``: the registered digest, the manifest, and no plasticity.

P1 addendum 2. The artifact is the clean reference of `d11-001`/`d12-001` —
digest ``ba95b605…``, every plastic KC->MBON gain at 1.0 — and the product
loop may never move it. The second half of this module runs the real loop over
the scripted chain of ``harness`` until an episode settles and asserts the
digest is where it started, which is the invariant the addendum asks for.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from flytrade import state as S
from tests.product import harness as H

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "brains" / "trader-v1"
REGISTERED = "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5"
GRAPH = "8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ARTIFACT / "manifest.json").read_text())


def test_the_artifact_loads_to_the_registered_digest():
    ck = S.load_checkpoint(ARTIFACT / "brain.npz", graph_sha256=GRAPH)
    assert S._digest(ck["gain"], ck["pos"], ck["graph_sha256"]) == REGISTERED
    assert len(ck["pos"]) == 44_042
    assert float(ck["gain"].min()) == float(ck["gain"].max()) == 1.0
    # a product journal that loaded a D12 branch's counters would read that
    # experiment's episode ids as its own settled markers
    assert int(ck["episode"]) == -1


def test_the_manifest_carries_every_field_addendum_2_names(manifest):
    assert manifest["state_digest"] == REGISTERED
    assert manifest["graph_sha256"] == GRAPH
    assert manifest["encoder"]["input_schema_sha256"] == (
        "3bf4f34c334a47cc960ad2619e091c4978f24d3eab0add63bb5c0a9501ff4615")
    assert manifest["encoder"]["version"] == "pons_encoder_v2"
    assert manifest["learning"] == "FROZEN"
    assert manifest["plastic_synapses"] == 44_042
    d11 = ROOT / manifest["d11_config"]["path"]
    assert sha256_file(d11) == manifest["d11_config"]["sha256"]
    assert manifest["provenance"]["run_ids"] == ["d10-001", "d11-001", "d12-001"]
    assert manifest["provenance"]["spec_commit"] == "f207679"


def test_the_committed_checkpoint_is_the_one_the_manifest_hashes(manifest):
    assert sha256_file(ARTIFACT / "brain.npz") == manifest["checkpoint"]["sha256"]


def test_the_manifest_records_the_two_checkpoints_it_was_verified_against(manifest):
    rows = manifest["provenance"]["checkpoints_compared"]
    names = {r["run_branch"] for r in rows}
    assert names == {"d11-001/frozen_reference", "d12-001/frozen_reference"}
    for row in rows:
        if not row.get("present"):
            continue
        assert row["gain_identical"] and row["pos_identical"]
        assert row["state_digest"] == REGISTERED


def test_the_artifact_is_the_constructed_clean_reference():
    """The weights are the ones the D11 construction produces, element by element."""
    import sys
    sys.path.insert(0, str(ROOT / "experiments" / "d11"))
    import common as C                                    # noqa: PLC0415

    cfg = json.loads((ROOT / "experiments" / "d11" / "config.json").read_text())
    _, mb, _, _, _, _, sha, clean = C.build_brain(cfg)
    ck = S.load_checkpoint(ARTIFACT / "brain.npz", graph_sha256=sha)
    assert clean == REGISTERED
    assert np.array_equal(ck["gain"], np.asarray(mb.gain, dtype=np.float32))
    assert np.array_equal(ck["pos"], np.asarray(mb.pos, dtype=np.int64))


# --------------------------------------------------- the no-plasticity invariant
@pytest.fixture(scope="module")
def settled(tmp_path_factory):
    """Forty ticks of the scripted chain, FROZEN, with one settled episode."""
    tmp = tmp_path_factory.mktemp("frozen")
    clock = H.Clock()
    head = 1_000
    logs = [H.pinned_launch(head + 2)] + H.trades(head + 5, 200, every=10)
    built = H.stack(tmp, clock=clock, logs=logs, head=head,
                    decoder=H.ScriptedDecoder(None, buys=1),
                    monkeypatch=None)
    H.stop_after(built, 40)
    out = built["loop"].run_branch()
    return built, out


def test_a_settled_episode_leaves_the_digest_exactly_where_it_was(settled):
    built, out = settled
    assert len(out["episodes"]) >= 1, "the fixture settled no episode"
    assert out["start_digest"] == REGISTERED
    assert out["end_digest"] == REGISTERED
    assert out["digest_unchanged"] is True
    assert built["loop"].journal.checkpoint_digest() == REGISTERED
    # and on disk, not only in memory
    ck = S.load_checkpoint(built["loop"].journal.checkpoint_path,
                           graph_sha256=GRAPH)
    assert S._digest(ck["gain"], ck["pos"], ck["graph_sha256"]) == REGISTERED


def test_the_settlement_was_frozen_and_wrote_no_learning_record(settled):
    built, out = settled
    lines = [json.loads(l) for l in
             built["loop"].journal.log.path.read_text().splitlines() if l.strip()]
    assert [e for e in lines if e["kind"] == "OUTCOME"]
    assert all(e.get("settlement") == "SETTLED_FROZEN"
               for e in lines if e["kind"] == "OUTCOME")
    assert not [e for e in lines if e["kind"] == "LEARNING"]
    assert all(e.get("settlement") == "SETTLED_FROZEN" for e in out["episodes"])


def test_the_loop_refuses_to_run_under_LEARN(tmp_path):
    from flytrade.product import live as PL
    with pytest.raises(ValueError, match="FROZEN"):
        PL.ProductLoop(feed=None, driver=None, run=None, mb=None, credit=None,
                       journal=None, encoder=None, admission=None,
                       execution=None, policy=None, universe=None,
                       mode="LIVE_PAPER", learning="LEARN", branch="live",
                       run_id="x")
