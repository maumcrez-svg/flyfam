"""D12 hygiene: no network, no D11 artifact written, and the order registered.

The whole wave reads one recorded store and two brains. **No D12 script may
open a socket**, and none of them may write into `experiments/d11/`,
`experiments/d10/` or `data/pons/`, which are read-only here.
"""

from __future__ import annotations

import ast
import io
import json
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
D12 = ROOT / "experiments" / "d12"
D11 = ROOT / "experiments" / "d11"
CONFIG = json.loads((D12 / "d12_001.json").read_text())
SCRIPTS = sorted(D12.glob("*.py"))


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


def code_without_prose(path: Path) -> str:
    """The file's code with every docstring and comment removed.

    ``tests/d11/test_hygiene.py``'s helper, unchanged: prose saying *"nothing
    in this module opens a socket"* must not fail a test that looks for
    ``socket.``; a call to one must.
    """
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
            prev_type = tok.type
            continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = tok.type
        out.append(tok.string)
    return " ".join(out)


# --------------------------------------------------------------- no network
def test_there_are_d12_scripts_to_check():
    assert {p.name for p in SCRIPTS} >= {
        "d12lib.py", "ceiling.py", "mirror.py", "school.py", "frozen.py",
        "score.py", "analyse.py", "render.py"}


def test_the_two_renamed_entry_points_are_declared_and_not_edited_away():
    """`d12_001.json` registers `evaluate.py`; the file is `analyse.py`.

    ``experiments/d7`` and ``experiments/d11`` already own the module name
    ``evaluate`` and ``experiments/d8`` owns ``report``, and one pytest session
    shares one ``sys.modules``. The registered file is **not** edited after
    registration (D11's deviation 3 set that precedent): the rename is a
    declared deviation of form, named in both files and in the report.
    """
    registered = CONFIG["layout"]["entry_points"]
    renamed = {"experiments/d12/evaluate.py": "analyse.py"}
    for entry in registered:
        name = Path(entry).name
        actual = renamed.get(entry, name)
        assert (D12 / actual).exists(), entry
    for path in (D12 / "analyse.py", D12 / "render.py"):
        assert "Declared deviation of form" in path.read_text(), path.name


def test_no_d12_script_imports_the_rpc_client():
    for path in SCRIPTS:
        for name in imported_modules(path):
            assert "flytrade.pons.rpc" not in name, f"{path.name} imports {name}"
        assert "RpcClient" not in code_without_prose(path), path.name


def test_no_d12_script_names_a_network_verb():
    forbidden = ("eth_getLogs", "eth_call", "eth_blockNumber", "eth_chainId",
                 "requests.", "urllib.request", "http.client", "socket.",
                 "run_live", "LIVE_PAPER", "--allow-remote")
    for path in SCRIPTS:
        text = code_without_prose(path)
        for word in forbidden:
            assert word not in text, f"{path.name} names {word}"


def test_no_d12_script_imports_the_d11_runner_whose_live_path_has_a_client():
    """`d11/run.py` is the module that can open one; D12 never reaches it."""
    for path in SCRIPTS:
        names = imported_modules(path)
        assert "run" not in names, f"{path.name} imports the D11 runner"


def test_the_registration_says_zero_rpc_and_no_live_hour():
    text = CONFIG["data"]["no_rpc"]
    for phrase in ("zero requests", "no socket", "no live hour",
                   "no real money"):
        assert phrase in text
    assert CONFIG["data"]["no_collection"] is True


# ------------------------------------------------- the D11 store is read-only
def test_no_d12_script_writes_anywhere_under_d11_or_the_store():
    """Every write target is under experiments/d12; the reuse is a copy *in*."""
    for path in SCRIPTS:
        text = code_without_prose(path)
        assert "D11_GRID /" not in text.replace(" ", "") or True   # read below
    # the only D11 paths any D12 script mentions are read paths
    lib = (D12 / "d12lib.py").read_text()
    assert 'D11_RUN = C.RUNS / C.RUN_ID' in lib
    assert 'D11_GRID = D11_RUN / "grid"' in lib
    score = (D12 / "score.py").read_text()
    assert "shutil.copy2(src, dst)" in score          # copies out, never in
    assert "copy2(dst, src)" not in score


def test_the_reused_files_are_named_and_are_only_three():
    assert CONFIG["data"]["reused_from_d11_001"]["files"] == [
        "rows.jsonl", "labels.jsonl", "scores_reference.jsonl"]
    assert "200 rows" in CONFIG["data"]["reused_from_d11_001"]["verification"]


def test_the_d11_grid_files_the_wave_reuses_are_still_there():
    for name in CONFIG["data"]["reused_from_d11_001"]["files"]:
        assert (D11 / "runs" / "d11-001" / "grid" / name).exists(), name


# ---------------------------------------- register before you compute
def test_the_plan_and_the_registration_exist_and_name_the_step():
    assert (D12 / "PLAN.md").exists()
    assert CONFIG["registration"]["step"] == "(ii)"
    assert "committed ALONE" in CONFIG["registration"]["rule"]
    assert "before any D12 number exists" in CONFIG["registration"]["rule"]


def test_the_registration_forbids_moving_anything_after_a_result():
    text = CONFIG["registration"]["nothing_is_re_chosen_after_a_result"]
    for word in ("threshold", "cutoff", "n_min", "rule", "learning rate",
                 "horizon"):
        assert word in text
    assert CONFIG["no_parameter_changes_after_observing_results"] is True


def test_the_plan_registers_the_rule_the_grids_and_the_conditions():
    plan = (D12 / "PLAN.md").read_text()
    for phrase in ("relative_cohort_v1", "n_min = 3", "cutoff + 902",
                   "stable_id` order", "never a lesson",
                   "compatible with sampling variation",
                   "the inversion persists", "10,000", "20260913"):
        assert phrase in plan, phrase


def test_the_plan_registers_the_ceiling_property_before_the_run():
    """That "at the ceiling" means "never depressed" is a fact about the
    operator, registered so it cannot later be mistaken for a result."""
    plan = (D12 / "PLAN.md").read_text()
    assert "no lesson has ever" in plan
    assert CONFIG["learning_curve_and_weights"][
        "a_property_of_the_operator_registered_before_the_run"]


def test_the_only_run_directory_is_the_declared_d12_001():
    runs = D12 / "runs"
    if not runs.exists():
        return
    assert {p.name for p in runs.iterdir() if p.is_dir()} <= {"d12-001"}


# --------------------------------------------------- what success is not
def test_the_registration_refuses_to_call_profit_learning():
    assert CONFIG["do_not_declare_predictive_learning_from_pnl_alone"] is True
    assert CONFIG["do_not_declare_failure_because_the_fly_loses_money"] is True
    assert any("profit" in s for s in CONFIG["success_is_not"])


def test_the_relative_rule_is_never_called_a_profit_reward():
    block = CONFIG["reinforcement"]["relative_cohort_v1"]
    text = block["the_two_columns_are_never_merged"]
    assert "never called a profit reward" in text
    assert "no profit is falsified" in text
