"""D11 hygiene: no network, no outcome in the fit, and the D10 logs unmoved.

The wave's own requirements: the D11 scripts import nothing from
``flytrade.pons.rpc``; the register-then-compute order is visible in the
artifacts; the scale fit contains no outcome vocabulary; and the D10 replay log
is still the log the determinism check signed.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
D11 = ROOT / "experiments" / "d11"
D10 = ROOT / "experiments" / "d10"
CONFIG = json.loads((D11 / "config.json").read_text())

#: D11-001 declares exactly three entry points that may talk to the local
#: node, and every other script in the directory may never open a socket. The
#: list is asserted to be complete, so a fourth one cannot appear quietly.
#: ``state_substitution.py`` joined them with the owner's amendment after
#: dispatch: its class (a) verification is a ledgered loopback probe.
NETWORK_ENTRY_POINTS = ("probe.py", "backfill.py", "run.py",
                        "state_substitution.py")
ALL_SCRIPTS = sorted(D11.glob("*.py"))
SCRIPTS = [p for p in ALL_SCRIPTS if p.name not in NETWORK_ENTRY_POINTS]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


# --------------------------------------------------------- no network
def test_the_network_entry_points_are_the_three_that_are_declared():
    """Nothing else in experiments/d11 may reach the chain, now or later."""
    reaches = set()
    for path in ALL_SCRIPTS:
        text = path.read_text()
        names = imported_modules(path)
        if (any("flytrade.pons.rpc" in n for n in names)
                or "RpcClient" in code_without_prose(path)):
            reaches.add(path.name)
    assert reaches == set(NETWORK_ENTRY_POINTS), sorted(reaches)


def test_the_replay_path_of_run_py_imports_no_client_at_module_level():
    """``run.py`` reaches the chain in ``--mode LIVE_PAPER`` and nowhere else.

    The rpc client is imported **inside** ``run_live``, as D10's runner does,
    so importing the module or running a replay branch cannot open a socket.
    """
    tree = ast.parse((D11 / "run.py").read_text())
    for node in tree.body:                       # module level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "rpc" not in alias.name.split(".")[-1], alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "flytrade.pons.rpc" not in node.module, node.module
    live = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "run_live")
    inside = {a.name for n in ast.walk(live) if isinstance(n, ast.ImportFrom)
              for a in n.names}
    assert {"RpcClient", "read_endpoint"} <= inside


def test_the_analysis_scripts_import_nothing_from_the_rpc_client():
    assert SCRIPTS, "there are D11 scripts to check"
    for path in SCRIPTS:
        for name in imported_modules(path):
            assert "flytrade.pons.rpc" not in name, f"{path.name} imports {name}"
        assert "RpcClient" not in code_without_prose(path), path.name


def code_without_prose(path: Path) -> str:
    """The file's code with every docstring and comment removed.

    Prose saying *"nothing in this module opens a socket"* must not fail a
    test that looks for ``socket.``; a call to one must.
    """
    import io
    import tokenize
    out: list[str] = []
    with open(path, "rb") as fh:
        tokens = list(tokenize.tokenize(fh.readline))
    prev_type = tokenize.INDENT
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            continue
        if (tok.type == tokenize.STRING
                and prev_type in (tokenize.INDENT, tokenize.NEWLINE,
                                  tokenize.NL, tokenize.ENCODING)):
            prev_type = tok.type          # a docstring, not a value
            continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = tok.type
        out.append(tok.string)
    return " ".join(out)


def test_the_analysis_scripts_name_no_network_verb():
    forbidden = ("eth_getLogs", "eth_call", "eth_blockNumber", "requests.",
                 "urllib.request", "http.client", "socket.")
    for path in SCRIPTS:
        text = code_without_prose(path)
        for word in forbidden:
            assert word not in text, f"{path.name} names {word}"


def test_the_v2_modules_import_nothing_from_the_rpc_client():
    for name in ("context_v2", "admission_v2", "encoder_v2"):
        path = ROOT / "flytrade" / "pons" / f"{name}.py"
        for imported in imported_modules(path):
            assert "rpc" not in imported.split(".")[-1], f"{name} imports {imported}"


# ------------------------------------------- no outcome enters the fit
#: words that would mean an outcome, a label or a return past the cutoff was
#: read. ``return`` itself is excluded: it is a Python keyword.
OUTCOME_WORDS = ("pnl", "net_pnl", "profit", "reward", "valence", "outcome",
                 "label", "auc", "settle", "realized", "realised", "survived")


def touched_names(path: Path) -> set[str]:
    """Every identifier and field name the file actually reads or writes.

    Parsed, not grepped, exactly as ``tests/d10/test_scales_hygiene.py`` does
    it: prose saying "no PnL is read anywhere in this file" must not fail the
    test, while ``record["net_pnl"]`` or ``outcome.net_pnl`` must.
    """
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


def test_the_scale_fit_touches_no_outcome_vocabulary():
    names = touched_names(D11 / "feature_scales_v2.py")
    for word in OUTCOME_WORDS:
        offenders = [n for n in names if word in n]
        assert not offenders, f"the scale fit touches {offenders}"


def test_the_retrospective_touches_no_outcome_vocabulary():
    """Section 6 of the amendment: it is a diagnostic, not a corrected PnL."""
    names = touched_names(D11 / "retrospective.py")
    for word in ("pnl", "net_pnl", "profit", "reward", "valence", "auc",
                 "realized", "realised"):
        offenders = [n for n in names if word in n]
        assert not offenders, f"the retrospective touches {offenders}"


def test_the_scale_artifact_declares_that_no_outcome_was_computed():
    fit = json.loads((D11 / "feature_scales_v2.json").read_text())
    assert fit["no_outcome_computed"] is True
    assert fit["fitted_features"] == ["trade_count_2m", "gross_volume_2m"]
    assert fit["grid_points_admitted"] == fit["statistics"][
        "trade_count_2m"]["n"]


def test_only_the_two_declared_features_were_fitted():
    fit = json.loads((D11 / "feature_scales_v2.json").read_text())
    d10 = json.loads((D10 / "config.json").read_text())["features"]["scales"]
    for name, value in CONFIG["features"]["scales"].items():
        if name in fit["scales"]:
            assert value == fit["scales"][name]
        elif name == "since_last_trade":
            assert value == 60.0, "the declared constant"
        else:
            assert value == d10[name], f"{name} moved and it should not have"


# ------------------------------------------ register before you compute
def test_the_registration_names_the_rule_before_the_value():
    plan = (D11 / "PLAN.md").read_text()
    assert "RULE X" in CONFIG["features"]["rule_x"] or "rule X" in plan
    assert "q = 90th percentile" in CONFIG["reinforcement"]["calibration_rule"]
    assert "max(old_full_scale, 2 * q)" in CONFIG["reinforcement"]["calibration_rule"]
    for name in ("trade_count_2m", "gross_volume_2m"):
        assert "FITTED BY RULE X" in CONFIG["features"]["scale_rules"][name]


def test_every_feature_has_a_scale_and_a_written_rule():
    order = CONFIG["features"]["order"]
    assert len(order) == 10
    for name in order:
        assert CONFIG["features"]["scales"][name] is not None
        assert CONFIG["features"]["scales"][name] > 0
        assert CONFIG["features"]["scale_rules"][name].strip()


def test_the_config_states_that_d11_runs_no_neural_experiment():
    text = CONFIG["d11_runs_no_neural_experiment"]
    for phrase in ("no historical and no live market-neural run",
                   "collects no new RPC data"):
        assert phrase in text


def test_the_next_run_is_declared_and_not_run():
    nxt = CONFIG["next_run"]
    assert nxt["id"] == "d11-001"
    assert "NOT RUN" in nxt["status"]
    assert nxt["from_clean_reference"] is True
    assert nxt["clean_reference_checkpoint"]["state_digest"].startswith(
        "ba95b60503d6")


def test_the_only_run_directory_is_the_declared_d11_001():
    """The D11 design wave started no run; ``d11-001`` is the one it declared.

    The invariant that matters is not that ``runs/`` is absent — the owner
    authorised ``d11-001`` — but that no *other* identity appeared beside it
    and that the design wave's own artifacts did not move.
    """
    runs = D11 / "runs"
    if not runs.exists():
        return
    declared = {"d11-001", "d11-live-001"}
    assert {p.name for p in runs.iterdir() if p.is_dir()} <= declared


# ------------------------------------------ the D10 artifacts are unmoved
def test_the_d10_replay_log_is_still_the_one_the_determinism_check_signed():
    """A check on existing logs. Nothing is re-run: the wave starts no run."""
    determinism = json.loads((D10 / "determinism.json").read_text())
    log = D10 / "runs" / "d10-001" / "learning" / "events.jsonl"
    if not log.exists():                       # the run directory is gitignored
        pytest.skip("the d10-001 run directory is not present in this checkout")
    h = hashlib.sha256()
    rows = 0
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for key in ("t", "path"):
            record.pop(key, None)
        h.update(json.dumps(record, sort_keys=True).encode())
        h.update(b"\n")
        rows += 1
    assert rows == determinism["lines"]
    assert h.hexdigest() == determinism["normalised_sha256"]
    assert determinism["normalised_sha256"] == \
        determinism["normalised_sha256_second"]


def test_the_reconciliation_and_the_calibration_agree_on_the_eight():
    recon = json.loads((D11 / "reconciliation.json").read_text())
    calib = json.loads((D11 / "reward_calibration.json").read_text())
    learned = {e["episode_id"] for e in recon["entries"] if e["learning"]}
    assert learned == {row["episode_id"] for row in calib["outcomes"]}
    assert recon["summary"]["entries"] == 17
    assert recon["summary"]["without_recent_activity"] == 15
    assert recon["summary"]["learning_updates"] == 8 == calib["n"]


def test_the_retrospective_says_it_is_not_a_backtest():
    text = (D11 / "retrospective.md").read_text()
    assert "not a backtest" in text
    assert "computes no trade the corrected brain" in text
    report = json.loads((D11 / "retrospective.json").read_text())
    assert report["not_a_backtest"]
    # fifteen of the seventeen entries fall to the recency rule
    excluded = [e for e in report["seventeen_entries"]
                if e["v2_verdict"] == "EXCLUDED"]
    assert len(excluded) == 15
    assert all(e["reasons"] == ["INACTIVE"] for e in excluded)
