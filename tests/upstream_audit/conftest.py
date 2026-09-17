"""
Make the vendored upstream importable and keep its global state out of the way.

``mushroom.MushroomBody`` resolves its persistence path at import time from
``FLY_STATE_DIR``; every test that touches it gets a fresh tmp dir so nothing
reads or writes the vendored tree.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "upstream"

if str(UPSTREAM) not in sys.path:
    sys.path.insert(0, str(UPSTREAM))


@pytest.fixture
def upstream_path():
    return UPSTREAM


@pytest.fixture
def mushroom(tmp_path, monkeypatch):
    """upstream ``mushroom`` with its store redirected at a tmp dir."""
    monkeypatch.setenv("FLY_STATE_DIR", str(tmp_path / "state"))
    import mushroom as m
    importlib.reload(m)
    # SHIPPED points into the vendored tree and must never be read either
    m.SHIPPED = tmp_path / "state" / "shipped-never-exists.npz"
    return m


@pytest.fixture
def flysim():
    import flysim
    return flysim
