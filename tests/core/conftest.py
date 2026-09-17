"""Fixtures for our own implementation's tests.

``tests/upstream_audit/`` tests unmodified upstream. This package tests
``flytrade/``. Both import upstream read-only; neither writes into it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "upstream"
REAL_DATA = ROOT / "data" / "malecns-v1.0"

for p in (str(ROOT), str(UPSTREAM)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="session")
def flysim():
    import flysim
    return flysim


@pytest.fixture
def synth(tmp_path):
    """Our three matrices over the synthetic mushroom-body graph."""
    from . import synthetic
    return synthetic.build(tmp_path)


def has_real_graph() -> bool:
    return (REAL_DATA / "graph.npz").exists() and \
           (REAL_DATA / "graph_mod.npz").exists() and \
           (REAL_DATA / "annotations.npz").exists()


requires_real_graph = pytest.mark.skipif(
    not has_real_graph(),
    reason="built connectome absent; run flytrade.graph.build over "
           "data/malecns-v1.0 (see data/MANIFEST.md)")


@pytest.fixture(scope="session")
def real(flysim):
    """(FlyBrain, ModulatoryGraph, Annotations) over the real connectome."""
    if not has_real_graph():
        pytest.skip("built connectome absent")
    from flytrade import graph as G, populations as P
    fb = flysim.FlyBrain(graph_path=REAL_DATA / "graph.npz")
    mod = G.ModulatoryGraph(REAL_DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(REAL_DATA / "annotations.npz")
    return fb, mod, ann
