"""The committed projections must be byte-identical before and after D10.

Addendum 13: ``records._compact`` drops the new fields for the old
projections, "so the five committed historical/D7 projections and every D9(b)
projection stay byte-identical before and after (asserted)".

This is that assertion, made the only way it can actually be made: the
pre-D10 ``observer/projection.py`` is read out of git at the baseline commit,
loaded beside the current one, and both are run over every event log on disk.
The two must produce the same bytes.

No fixture is involved. If the logs are not on disk (they are gitignored
run output) the test skips and says so rather than passing vacuously.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
#: the commit D10 started from. The projection at this commit is what "before"
#: means.
BASELINE = "5dc5704"
ROOTS = (ROOT / "experiments" / "historical" / "runs",
         ROOT / "experiments" / "d7" / "runs",
         ROOT / "experiments" / "d9b" / "runs")


def _logs() -> list[Path]:
    out = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for run in sorted(root.iterdir()):
            if not run.is_dir():
                continue
            for branch in sorted(run.iterdir()):
                log = branch / "events.jsonl"
                if log.is_file():
                    out.append(log)
    return out


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def before(tmp_path_factory):
    try:
        source = subprocess.run(
            ["git", "show", f"{BASELINE}:observer/projection.py"],
            cwd=str(ROOT), check=True, capture_output=True, text=True).stdout
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"cannot read the baseline projection from git: {exc}")
    path = tmp_path_factory.mktemp("baseline") / "projection_before.py"
    path.write_text(source)
    return _load("projection_before", path)


@pytest.fixture(scope="module")
def after():
    return _load("projection_after", ROOT / "observer" / "projection.py")


#: The one field of ``meta`` that a later wave does move, and the reason it has
#: to. ``kind_vocabulary`` is the *contract's* list of event kinds, not this
#: run's content. D10 adds ``DISCOVERY`` and ``UNRESOLVED`` to the vocabulary
#: and D12 adds ``LESSON``, so the list grows for every log alike — including
#: logs that contain none of them. Suppressing that would make the contract lie
#: about what a frame can be; the honest assertion is that the **frames** are
#: byte-identical and that this is the only thing in ``meta`` that moved.
#: Declared, not quietly excluded.
VOCABULARY_KEY = "kind_vocabulary"

#: every kind added to the vocabulary since ``BASELINE``
ADDED_KINDS = {"DISCOVERY", "UNRESOLVED", "LESSON",
               # P1: the product feed's nine
               "SNIFF", "PICK", "OPEN", "MARK", "CLOSE", "CREDIT",
               "HEARTBEAT", "THROTTLED", "RPC_ERROR"}


def _digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


@pytest.mark.parametrize("log", _logs(), ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_the_frames_of_every_committed_log_are_byte_identical(log, before, after):
    old = before.project(before.read_log(log))
    new = after.project(after.read_log(log))
    assert _digest(old["frames"]) == _digest(new["frames"])
    assert len(old["frames"]) == len(new["frames"])


@pytest.mark.parametrize("log", _logs(), ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_only_the_declared_kind_vocabulary_moved_in_meta(log, before, after):
    old = before.project(before.read_log(log))["meta"]
    new = after.project(after.read_log(log))["meta"]
    moved = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    assert moved == {VOCABULARY_KEY}
    assert set(new[VOCABULARY_KEY]) - set(old[VOCABULARY_KEY]) == ADDED_KINDS


def test_there_were_logs_to_check():
    """A vacuous pass is not a pass."""
    logs = _logs()
    if not logs:
        pytest.skip("no D5/D6, D7 or D9(b) run logs on disk to project")
    assert len(logs) >= 3


def test_the_new_kinds_appear_in_no_earlier_log():
    """Which is why adding them cannot move an earlier projection."""
    for log in _logs():
        text = log.read_text()
        for kind in sorted(ADDED_KINDS):
            assert f'"kind": "{kind}"' not in text


def test_compact_drops_every_field_d10_added(after):
    """Each new payload key is ``None`` for an old event and is dropped."""
    old_decision = {"kind": "DECISION", "decoded_action": "BUY",
                    "readout_status": "VALID", "symbol": "IBM",
                    "observation": {"normalized": {"r1": 0.1, "r5": 0.2,
                                                   "r20": 0.3, "rv20": 0.4,
                                                   "relvol": 0.5}}}
    payload = after._payload(old_decision, [])
    for key in ("venue", "chain_id", "mode", "learning_mode", "token", "curve",
                "block_number", "age_s", "marginal_price", "last_trade_price",
                "executable_tokens_out"):
        assert key not in payload
    old_round = {"kind": "ROUND", "candidates": [], "round_index": 1}
    round_payload = after._payload(old_round, [])
    for key in ("venue", "mode", "learning_mode", "admitted", "rotated",
                "discovered", "tracked", "mark", "context"):
        assert key not in round_payload


def test_the_feature_order_falls_back_to_the_five_for_an_old_log(after):
    old = [{"kind": "DECISION",
            "observation": {"normalized": {"r1": 0.0, "r5": 0.0, "r20": 0.0,
                                           "rv20": 0.0, "relvol": 0.0}}}]
    assert after._feature_names(old) == after.FEATURES
    assert after._feature_names([]) == after.FEATURES


def test_the_feature_order_follows_a_d10_log(after):
    new = [{"kind": "DECISION",
            "observation": {"normalized": {"age": 0.0, "ret_30s": 0.0,
                                           "ret_2m": 0.0, "ret_5m": 0.0,
                                           "flow_imb_2m": 0.0,
                                           "trade_rate_2m": 0.0,
                                           "rv_2m": 0.0, "drawdown_5m": 0.0}}}]
    assert after._feature_names(new)[0] == "age"
    assert len(after._feature_names(new)) == 8
