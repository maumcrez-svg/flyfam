"""The scales were registered, not fitted to an outcome.

Reviewer decision 3 asks that the scale statistics be computed "before any
outcome, PnL or post-cutoff return is computed". That is a claim about a
script, and this checks the script: no outcome vocabulary appears in it, the
artifact it wrote says so, and the scale values in `config.json` are exactly
the ones the artifact recorded.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "experiments" / "d10"
SCRIPT = HERE / "feature_scales_v2.py"
ARTIFACT = HERE / "feature_scales_v2.json"
CONFIG = HERE / "config.json"
PROBE = HERE / "probe.py"

#: words that would mean an outcome, a label or a return past the cutoff was
#: read. ``return`` itself is excluded: it is a Python keyword.
OUTCOME_WORDS = ("pnl", "net_pnl", "profit", "reward", "valence", "outcome",
                 "label", "auc", "settle", "realized", "realised")


def _touched_names(path: Path) -> set[str]:
    """Every identifier and every field name the file actually reads or writes.

    Parsed, not grepped: a docstring saying "no PnL is read anywhere in it" is
    prose and must not fail the test, while ``event["net_pnl"]`` or
    ``outcome.net_pnl`` must. So this collects names, attributes, subscript
    keys and ``.get(...)`` keys, and nothing else.
    """
    import ast
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                names.add(node.slice.value.lower())
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "get"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                names.add(node.args[0].value.lower())
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name.lower())
    return names


def test_the_scale_script_reads_no_outcome():
    names = _touched_names(SCRIPT)
    for word in OUTCOME_WORDS:
        hits = [n for n in names if word in n]
        assert not hits, f"feature_scales_v2.py touches {hits}"


def test_the_probe_reads_no_outcome_and_no_pnl():
    """Addendum 9: "no PnL anywhere in it"."""
    names = _touched_names(PROBE)
    for word in ("pnl", "profit", "outcome", "label", "auc", "settle"):
        hits = [n for n in names if word in n]
        assert not hits, f"probe.py touches {hits}"


def test_the_artifact_records_that_it_computed_no_outcome():
    report = json.loads(ARTIFACT.read_text())
    assert report["no_outcome_computed"] is True
    assert report["computed_before"] == ["experiments/d10/PLAN.md",
                                         "experiments/d10/config.json"]
    assert report["scale_window_minutes"] == 60
    assert report["min_age_seconds"] == 60
    assert report["min_trades"] == 3


def test_the_config_carries_exactly_the_scales_the_artifact_recorded():
    report = json.loads(ARTIFACT.read_text())
    cfg = json.loads(CONFIG.read_text())
    assert cfg["features"]["scales"] == report["scales"]
    assert cfg["features"]["scale_artifact"] == "experiments/d10/feature_scales_v2.json"


def test_the_age_scale_is_declared_and_not_fitted():
    report = json.loads(ARTIFACT.read_text())
    assert report["features"]["age"]["scale"] == 600.0
    assert "declared constant" in report["features"]["age"]["rule"]
    for name, row in report["features"].items():
        if name == "age":
            continue
        assert row["rule"] == "p90(|x|) rounded to two significant figures"



def test_the_rounding_rule_is_what_it_says():
    import importlib.util
    spec = importlib.util.spec_from_file_location("d10_scales", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.two_significant_figures(0.00509908469970584) == 0.0051
    assert module.two_significant_figures(0.3566783892166435) == 0.36
    assert module.two_significant_figures(6.0) == 6.0
    report = json.loads(ARTIFACT.read_text())
    for name, row in report["features"].items():
        if name == "age":
            continue
        assert row["scale"] == module.two_significant_figures(row["p90_abs"])


def test_the_plan_and_config_commit_precedes_the_run():
    """Register-then-compute, checked against git rather than asserted in prose."""
    def commit(path):
        return subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", path], cwd=str(ROOT),
            capture_output=True, text=True, check=True).stdout.strip()

    def when(sha):
        return int(subprocess.run(["git", "show", "-s", "--format=%ct", sha],
                                  cwd=str(ROOT), capture_output=True, text=True,
                                  check=True).stdout.strip())

    config_commit = commit("experiments/d10/config.json")
    plan_commit = commit("experiments/d10/PLAN.md")
    if not config_commit or not plan_commit:
        pytest.skip("not a git checkout")
    assert config_commit == plan_commit          # committed together, and alone
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", config_commit], cwd=str(ROOT),
        capture_output=True, text=True, check=True).stdout.split()
    assert sorted(files) == ["experiments/d10/PLAN.md",
                             "experiments/d10/config.json"]
    summary_path = ROOT / "experiments" / "d10" / "runs" / "d10-001" / "summary.json"
    if not summary_path.exists():
        pytest.skip("d10-001 has not been run; its output is gitignored")
    assert summary_path.stat().st_mtime > when(config_commit)
