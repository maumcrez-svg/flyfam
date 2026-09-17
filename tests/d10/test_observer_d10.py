"""The D10 wave root, and the isolation the viewer has always had.

The serve process must never import the chain client. Everything else here is
the third wave root appearing in ``/api/runs`` and ``/api/summary`` with the
four terms addendum 13 names, and ``/api/presentation`` projecting a D10 log.

The log used is the one this wave's run wrote; if it is not on disk the tests
that need it skip and say so.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "observer"
RUNS = ROOT / "experiments" / "d10" / "runs"
sys.path.insert(0, str(OBSERVER))


@pytest.fixture(scope="module")
def serve():
    for name in ("serve", "projection"):
        sys.modules.pop(name, None)
    module = importlib.import_module("serve")
    return module


def test_the_serve_process_does_not_import_the_chain_client():
    """Addendum 13, the mechanical half: no RPC is reachable from the viewer.

    Checked in a **subprocess**, because this test session has already imported
    :mod:`flytrade` for other reasons and an in-process check would be
    answering the wrong question.
    """
    import subprocess
    probe = (
        "import sys; sys.path.insert(0, %r); import serve;"
        "bad = sorted(m for m in sys.modules if m.startswith('flytrade'));"
        "print(','.join(bad))" % str(OBSERVER))
    out = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT),
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
    source = (OBSERVER / "serve.py").read_text()
    assert "flytrade.pons" not in source
    assert "import flytrade" not in source
    projection = (OBSERVER / "projection.py").read_text()
    code = "\n".join(line for line in projection.splitlines()
                      if not line.lstrip().startswith("#"))
    assert "import flytrade" not in code
    assert "flytrade.pons" not in code


def test_the_d10_wave_root_exists_and_is_the_third_one(serve):
    waves = [r["wave"] for r in serve.ROOTS]
    # A later wave may append a root; it may never move D10's. The invariant
    # is the prefix and D10's position in it, not the total count.
    assert waves[:4] == ["D5/D6", "D7", "D9(b)", "D10"]
    assert waves.index("D10") == 3
    d10 = serve.ROOTS[3]
    assert d10["runs"] == RUNS
    assert set(d10["extra"]) >= {"plan", "deployments", "probes", "scales"}


def test_wave_labels_say_pons_replay_paper_and_the_learning_mode(serve):
    summary = {"venue": "PONS", "chain_id": 4663,
               "config": {"dataset": {"label": "d10-backfill-v1"}},
               "branches": {"learning": {"mode": "REPLAY_PAPER",
                                         "learning": "LEARN"},
                            "frozen_reference": {"mode": "REPLAY_PAPER",
                                                 "learning": "FROZEN"}}}
    labels = serve.wave_labels("d10-001", summary)
    assert labels["venue"] == "PONS"
    assert labels["data"] == "REPLAY"
    assert labels["execution"] == "PAPER"
    assert set(labels["learning"]) == {"LEARN", "FROZEN"}
    assert labels["label"] == "PONS / REPLAY / PAPER / FROZEN+LEARN"
    assert labels["dataset"] == "d10-backfill-v1"


def test_a_live_run_is_labelled_LIVE(serve):
    summary = {"venue": "PONS", "chain_id": 4663,
               "branches": {"live": {"mode": "LIVE_PAPER", "learning": "LEARN"}}}
    labels = serve.wave_labels("d10-live-001", summary)
    assert labels["data"] == "LIVE"
    assert labels["label"] == "PONS / LIVE / PAPER / LEARN"


def test_an_earlier_wave_gets_no_pons_block(serve):
    assert serve.wave_labels("hist-001", {"run_id": "hist-001"}) == {}
    assert serve.wave_labels("hist-001", None) == {}


@pytest.fixture
def run_id():
    if not (RUNS / "d10-001" / "summary.json").exists():
        pytest.skip("d10-001 has not been run; its output is gitignored")
    return "d10-001"


def test_the_run_is_listed_with_its_branches_and_its_pons_block(serve, run_id):
    rows = [r for r in serve.list_runs() if r["run_id"] == run_id]
    assert len(rows) == 1
    row = rows[0]
    assert row["wave"] == "D10"
    assert {b["branch"] for b in row["branches"]} >= {"learning"}
    assert row["pons"]["venue"] == "PONS"
    assert row["pons"]["execution"] == "PAPER"


def test_the_summary_is_found_inside_the_run_directory(serve, run_id):
    summary = serve.summary_for(run_id)
    assert summary is not None
    assert summary["run_id"] == run_id
    assert summary["venue"] == "PONS"
    assert summary["chain_id"] == 4663


def test_the_presentation_projects_a_d10_log_with_its_context_and_mark(serve,
                                                                      run_id):
    import projection as PJ
    log = RUNS / run_id / "learning" / "events.jsonl"
    stream = PJ.load(log, summary=serve.summary_for(run_id))
    assert stream["meta"]["frames"] == stream["meta"]["events"]
    assert stream["meta"]["features"][0] == "age"
    assert len(stream["meta"]["features"]) == 8
    kinds = stream["meta"]["kinds"]
    assert kinds.get("DISCOVERY", 0) > 0
    assert kinds.get("DECISION", 0) > 0
    decisions = [f for f in stream["frames"] if f["kind"] == "DECISION"]
    assert decisions
    assert all(f["ev"]["venue"] == "PONS" for f in decisions)
    assert any("token" in f["ev"] for f in decisions)
    rounds = [f for f in stream["frames"] if f["kind"] == "ROUND"]
    assert any("mark" in f["ev"] for f in rounds)
    assert any("context" in f["ev"] for f in rounds)


def test_no_endpoint_or_key_reaches_the_presentation(serve, run_id):
    import projection as PJ
    log = RUNS / run_id / "learning" / "events.jsonl"
    body = json.dumps(PJ.load(log, summary=serve.summary_for(run_id)))
    for forbidden in ("http://", "https://", "p2pify", "chainstack", "apikey"):
        assert forbidden not in body.lower()
