"""
Isolation guards — Fable addendum 10, and §6's "no runtime path".

The diagnostic models are external measurement tools with supervised access to
historical labels. They must not be able to reach the decoder, an order, a
reward, a plastic weight or an observer decision, and nothing in this wave may
move a D7 artifact.

Three guards, all mechanical:

1. **No module under `experiments/d8/` imports** ``flytrade.execution``,
   ``flytrade.runner``, ``flytrade.mushroom``, ``flytrade.state`` or
   ``flytrade.readout``. The check is a static AST scan of the committed
   sources, because a transitive import is unavoidable and is declared instead:
   ``flytrade.historical`` — needed to read the price file causally — imports
   ``flytrade.execution``, and ``flytrade.records`` — which Fable addendum 11
   *requires* the alignment audit to parse the log with — imports
   ``flytrade.runner`` and ``flytrade.state``. What matters is that no D8 module
   ever *names* one of those APIs, which guard 2 checks.
2. **No D8 source calls a mutating API**: no order, no fill, no reinforcement,
   no weight update, no checkpoint write, no bankroll.
3. **The observer is untouched** and the six `d7-001` artifacts still carry the
   hashes the plan registered before any D8 number existed.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D8 = ROOT / "experiments" / "d8"
CONFIG = json.loads((D8 / "config.json").read_text())
GRIDS = json.loads((D8 / "grids.json").read_text())

FORBIDDEN_IMPORTS = tuple(CONFIG["isolation"]["no_direct_import_of"])

#: identifiers that would mean "this module can move money, weights or an
#: order". They are matched as **names and attributes in the parsed syntax
#: tree**, never as substrings of prose: an audit that reports a reinforcement
#: sign has to be able to write the word "reinforcement" in a docstring.
MUTATORS = frozenset((
    "ExecutionPolicy", "MushroomBody", "CreditAssigner", "FlyBrain",
    "record_learning", "open_episode", "settle_episode", "apply_outcome",
    "reinforce", "depress", "learn", "forget", "save_checkpoint",
    "write_pending", "clear_pending", "place_order", "submit", "buy", "sell",
    "run_branch", "decode", "decode_rates", "present"))


def d8_sources() -> list[Path]:
    return sorted(p for p in D8.rglob("*.py") if "__pycache__" not in p.parts)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:                       # relative import
                mod = "." * node.level + mod
            out.add(mod)
            out.update(f"{mod}.{a.name}" for a in node.names)
    return out


def test_there_are_d8_modules_to_check():
    assert len(d8_sources()) >= 2


def test_no_d8_module_imports_the_loop():
    offenders = []
    for p in d8_sources():
        for mod in imported_modules(p):
            if mod in FORBIDDEN_IMPORTS:
                offenders.append(f"{p.relative_to(ROOT)}: {mod}")
    assert offenders == []


def identifiers(path: Path) -> set[str]:
    """Every name and attribute the module actually refers to."""
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.add(node.name)
    return out


def test_no_d8_module_names_a_mutating_api():
    offenders = []
    for p in d8_sources():
        for name in sorted(identifiers(p) & MUTATORS):
            offenders.append(f"{p.relative_to(ROOT)}: {name}")
    assert offenders == []


#: account-shaped identifiers. Matched in the syntax tree, not in prose: a
#: report that promises it holds no bankroll has to be able to say the word.
ACCOUNT_NAMES = frozenset((
    "cash", "bankroll", "equity", "realized_pnl", "realised_pnl",
    "fees_paid", "slippage_paid", "initial_cash", "account", "position",
    "cumulative_realized_pnl"))


def test_the_counterfactual_outcomes_cannot_reach_a_bankroll():
    """No D8 module reads or holds an account, a cash balance or a PnL ledger."""
    offenders = []
    for p in d8_sources():
        for name in sorted(identifiers(p) & ACCOUNT_NAMES):
            offenders.append(f"{p.relative_to(ROOT)}: {name}")
    assert offenders == []


def test_the_observer_knows_nothing_about_d8():
    text = (ROOT / "observer" / "serve.py").read_text()
    assert "experiments/d8" not in text
    assert "d8" not in json.dumps(
        [ln for ln in text.splitlines() if "experiments" in ln])


def test_nothing_under_experiments_d8_writes_into_experiments_d7():
    needle = "experiments/" + "d7"
    for p in d8_sources():
        for n, line in enumerate(p.read_text().splitlines(), start=1):
            if needle in line:
                assert "write" not in line.lower(), f"{p}:{n}"


def test_the_registered_artifacts_still_carry_their_registered_hashes():
    """Recorded by ``grids.py``, and re-checked live when the files are here."""
    import hashlib
    registered = CONFIG["artifacts"]
    found = GRIDS["artifact_hashes_found"]
    assert set(found) == set(registered)
    assert found == registered
    for rel, want in registered.items():
        p = ROOT / rel
        if not p.exists():                 # gitignored run store on a clone
            continue
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == want, rel


def test_the_checkpoints_and_the_three_event_logs_are_in_the_registration():
    keys = set(CONFIG["artifacts"])
    for branch in ("learned", "frozen_trained", "frozen_reference"):
        assert f"experiments/d7/runs/d7-001/{branch}/events.jsonl" in keys
        assert f"experiments/d7/runs/d7-001/{branch}/brain.npz" in keys
