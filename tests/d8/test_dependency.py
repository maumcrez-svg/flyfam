"""
The `diagnostics` extra is present, pinned, and does not move the stack.

Fable addendum 7: scikit-learn is declared as a new optional extra, pinned to
the version `experiments/d8/PLAN.md` and `config.json` record, and the D8 tests
import it **directly** — no `importorskip`. The gate must fail loudly, never
skip, if the extra is missing. The frozen numpy / scipy pins are asserted here
too, because the whole point of the pin is that installing the diagnostic did
not move the production stack.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import numpy
import scipy
import sklearn                                   # no importorskip, by rule

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "experiments" / "d8" / "config.json").read_text())


def test_extra_is_declared_and_pinned():
    pp = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = pp["project"]["optional-dependencies"]
    assert extras["diagnostics"] == ["scikit-learn==1.9.1"]
    assert extras["dev"] == ["pytest==9.1.1"]


def test_main_dependencies_are_untouched():
    pp = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pp["project"]["dependencies"] == [
        "numpy==2.4.2", "scipy==1.17.1", "pandas==3.0.1", "pyarrow==23.0.1"]


def test_installed_versions_match_the_plan():
    dep = CONFIG["dependency"]
    assert dep["pin"] == f"scikit-learn=={sklearn.__version__}"
    assert dep["resolved_against"]["numpy"] == numpy.__version__
    assert dep["resolved_against"]["scipy"] == scipy.__version__


def test_the_plan_and_config_were_committed_before_any_number():
    assert CONFIG["committed_alone_before_any_d8_number"] is True
    assert CONFIG["label"] == "RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY OBSERVED"
    assert CONFIG["models"]["primary"] == "NONLINEAR on X_SENSORY"
