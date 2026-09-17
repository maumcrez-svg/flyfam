"""
The viewer cannot reach the worker. Amendment D9(a) §8, addendum 4.

"Do not import a worker startup path that can trigger trading or learning just
to render the viewer." D8 risk 6 recorded why this needs a mechanical test
rather than a promise: ``flytrade.records`` imports ``runner`` and ``state``
transitively, so one convenience import in the observer would pull the whole
execution stack — and its module-level side effects — into the process that
serves a web page.

So the observer modules duplicate the ten canonical event kinds and the four
readout statuses as plain strings, and these tests hold the duplicate to the
original: **this** file may import :mod:`flytrade.records`, and it asserts the
two vocabularies are equal. The observer modules are imported in a *subprocess*
so the assertion is about what they pull in, not about what the rest of the
pytest session happened to import first.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "observer"
sys.path.insert(0, str(OBSERVER))

import projection as P                                  # noqa: E402

# the one import of flytrade in the whole of tests/observer, and it is here
from flytrade import decoder as D                       # noqa: E402
from flytrade import records as REC                     # noqa: E402


def test_the_projection_kinds_are_exactly_the_canonical_event_types():
    assert set(P.KINDS) == {e.value for e in REC.EventType}
    assert len(P.KINDS) == 22          # D10 added DISCOVERY and UNRESOLVED,
                                       # D12 added LESSON, P1 the nine kinds
                                       # of the product feed
    for name in ("ROUND", "ROUND_ABORTED", "DECISION", "EXECUTION", "OUTCOME",
                 "LEARNING", "CHECKPOINT", "RECOVERY", "WARMUP", "PARTITION"):
        assert getattr(P, name) == getattr(REC.EventType, name).value


def test_the_projection_readout_statuses_are_exactly_the_decoder_s():
    assert set(P.READOUT_STATUSES) == {s.value for s in D.ReadoutStatus}
    assert set(P.ACTIONS) == {a.value for a in D.Action}
    assert P.VALID == D.ReadoutStatus.VALID.value
    assert P.NO_RESPONSE == D.ReadoutStatus.NO_RESPONSE.value
    assert P.INVALID_STATE == D.ReadoutStatus.INVALID_STATE.value
    assert P.POLICY_REJECT == D.ReadoutStatus.POLICY_REJECT.value


def test_the_replicate_legend_covers_every_readout_status():
    assert set(P.STATUS_LETTER) == {s.value for s in D.ReadoutStatus}
    assert len(set(P.STATUS_LETTER.values())) == len(P.STATUS_LETTER)


def _subprocess_modules(module: str) -> set[str]:
    """Import one observer module in a clean interpreter; report sys.modules."""
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(OBSERVER)!r})\n"
        f"import {module}\n"
        "print(json.dumps(sorted(m for m in sys.modules "
        "if m.split('.')[0] in ('flytrade', 'numpy', 'scipy', 'pandas', "
        "'pyarrow', 'sklearn'))))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    import json as _json
    return set(_json.loads(out.stdout.strip().splitlines()[-1]))


def test_importing_the_projection_pulls_in_no_flytrade_and_no_numpy():
    assert _subprocess_modules("projection") == set()


def test_importing_the_server_pulls_in_no_flytrade_and_no_numpy():
    assert _subprocess_modules("serve") == set()


def test_no_observer_module_imports_anything_outside_the_standard_library():
    """Read the imports out of the AST, not out of the prose."""
    import ast
    # standard library only, by name. D10 adds `os` and `time`: the live
    # health block's `fresh` rule is now-relative and the worker's liveness is
    # a pid file plus a heartbeat mtime, and both are read-time facts computed
    # from files the worker wrote. Nothing third-party is allowed in either.
    allowed = {"json", "sys", "gzip", "pathlib", "http", "urllib", "os",
               "time", "projection", "__future__"}
    for f in sorted(OBSERVER.glob("*.py")):
        tree = ast.parse(f.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        assert names <= allowed, f"{f.name}: {sorted(names - allowed)}"
        # and no attribute access reaches the package by name either
        src_code = "\n".join(
            ln for ln in f.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith(("#", "*")))
        assert "flytrade." not in src_code, f.name


def test_the_observer_never_opens_a_checkpoint_or_a_dataset():
    for f in sorted(OBSERVER.glob("*.py")):
        src = f.read_text()
        code = [ln for ln in src.splitlines()
                if ln.strip() and not ln.lstrip().startswith(("#", "*"))]
        joined = "\n".join(code)
        # the vendor download directory, assembled so this line does not
        # name it (tests/historical/test_vendor_format.py holds the rule)
        for forbidden in (".npz", ".feather", "data/" + "mar" + "ket",
                          "np.load", "savez", "pickle"):
            assert forbidden not in joined, f"{f.name}: {forbidden}"
