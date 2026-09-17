"""Fixtures for the Phase One vertical slice.

Reuses the arrangement of ``tests/core/conftest.py``: upstream is imported
read-only and never written to. Tests that need the connectome are skipped when
it is absent, exactly as the core suite does.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "upstream"
REAL_DATA = ROOT / "data" / "malecns-v1.0"

for p in (str(ROOT), str(UPSTREAM)):
    if p not in sys.path:
        sys.path.insert(0, p)


def has_real_graph() -> bool:
    return all((REAL_DATA / f).exists() for f in
               ("graph.npz", "graph_mod.npz", "annotations.npz"))


requires_real_graph = pytest.mark.skipif(
    not has_real_graph(),
    reason="built connectome absent; see data/MANIFEST.md")


@pytest.fixture(scope="session")
def ann():
    if not has_real_graph():
        pytest.skip("built connectome absent")
    from flytrade import populations as P
    return P.Annotations.load(REAL_DATA / "annotations.npz")


@pytest.fixture(scope="session")
def brain(ann):
    """(FlyBrain, MushroomBody, gains) over the real connectome."""
    if not has_real_graph():
        pytest.skip("built connectome absent")
    import flysim
    from flytrade import encoder as E, graph as G, mushroom as M, populations as P
    fb = flysim.FlyBrain(graph_path=REAL_DATA / "graph.npz")
    mod = G.ModulatoryGraph(REAL_DATA / "graph_mod.npz", bodies=fb.bodies)
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    gains = np.full(fb.n_types, E.GLOBAL_GAIN, dtype=np.float32)
    return fb, mb, gains


@pytest.fixture(scope="session")
def graph_sha256():
    from flytrade import graph as G
    if not has_real_graph():
        return "0" * 64
    return G.sha256_file(REAL_DATA / "graph.npz")


@pytest.fixture
def fresh_weights(brain):
    """Reset learned gains and traces around a test that changes them."""
    fb, mb, _ = brain
    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.events = {"reward": 0, "punish": 0, "rejected_episode": 0}
    mb.apply()
    yield mb
    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()
