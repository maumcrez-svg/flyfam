"""
The same proofs, on the real MaleCNS v1.0 connectome.

Skipped when ``data/malecns-v1.0/graph.npz`` is absent — the connectome is
CC-BY, ~1 GB of feather, and is never committed (`data/MANIFEST.md`).
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import graph as G
from flytrade import mushroom as M
from flytrade import populations as P

from .conftest import requires_real_graph

pytestmark = requires_real_graph


@pytest.fixture(scope="module")
def mb(real):
    fb, mod, ann = real
    kc = np.flatnonzero(P.kenyon_cells(ann))
    mbon = np.flatnonzero(P.mbons(ann))
    pam = np.flatnonzero(P.pam(ann))
    ppl1 = np.flatnonzero(P.ppl1(ann))
    return M.MushroomBody(fb, mod, kc, mbon, pam, ppl1)


def test_the_three_matrices_share_one_index(real):
    fb, mod, ann = real
    assert fb.n == 165_122
    assert np.array_equal(mod.bodies, fb.bodies)
    assert np.array_equal(ann.bodies, fb.bodies)
    assert mod.D.shape == fb.W.shape


def test_population_counts_are_the_measured_ones(real):
    fb, mod, ann = real
    assert int(P.kenyon_cells(ann).sum()) == 4064
    assert int(P.mbons(ann).sum()) == 97
    assert int(P.pam(ann).sum()) == 316
    assert int(P.ppl1(ann).sum()) == 16
    assert int(P.apl(ann).sum()) == 2
    assert int(P.orns(ann).sum()) == 2635
    assert int(P.by_type(ann, "DNa02").sum()) == 2


def test_kc_to_mbon_synapse_count_matches_the_anatomy(mb):
    assert len(mb.pos) == 44_042
    assert len(mb.pre) == len(mb.post) == len(mb.pos)


def test_the_fast_matrix_has_no_dan_to_mbon_edge_at_all(real, mb):
    """Part 1 of the fix is necessary on the real data too: upstream's sign
    rule leaves nothing to read."""
    fb, mod, ann = real
    pam = np.flatnonzero(P.pam(ann))
    ppl1 = np.flatnonzero(P.ppl1(ann))
    assert np.abs(fb.W[mb.mbon][:, pam]).sum() == 0.0
    assert np.abs(fb.W[mb.mbon][:, ppl1]).sum() == 0.0
    # while the modulatory matrix has 39,616 of them onto MBONs
    assert mod.input_weight(mb.mbon, pam).sum() == 28_546.0
    assert mod.input_weight(mb.mbon, ppl1).sum() == 11_070.0


def test_the_corrected_compartment_split_on_the_real_connectome(mb):
    c = mb.compartments
    assert len(c.pam_side) == 41
    assert len(c.ppl1_side) == 56
    assert len(c.unclassified) == 0
    assert int((mb.side == 1).sum()) == 24_005
    assert int((mb.side == -1).sum()) == 20_037


def test_mbon01_to_10_are_pam_side_and_mbon11_to_15_are_ppl1_side(real, mb):
    """The hemibrain compartment map, reproduced by the corrected read.

    This is a *literature* expectation (Aso et al. 2014 eLife 3:e04577;
    Li et al. 2020 eLife 9:e62576), not a measurement from this dataset, and
    it is asserted here only because it is the strongest available external
    check that the corrected read finds real structure. See
    ``docs/POPULATIONS.md`` ambiguity 1.
    """
    fb, mod, ann = real
    side = mb.compartments.side
    for n in range(1, 11):
        idx = np.flatnonzero(ann.type == f"MBON{n:02d}")
        if not len(idx):
            continue
        assert set(side[idx].tolist()) == {1}, f"MBON{n:02d} should be PAM-side"
    for n in range(11, 16):
        idx = np.flatnonzero(ann.type == f"MBON{n:02d}")
        assert len(idx)
        assert set(side[idx].tolist()) == {-1}, f"MBON{n:02d} should be PPL1"


def test_the_split_differs_materially_from_upstreams(real, mb):
    """Run unmodified upstream over the same graph.npz and diff the answer.

    Not a claim that upstream is broken *here* — ``tests/upstream_audit``
    already proves that on a graph whose orientation is known. This pins the
    size of the consequence on the real connectome.
    """
    fb, mod, ann = real
    import mushroom as upstream_mushroom
    ub = upstream_mushroom.MushroomBody(fb)
    assert np.array_equal(ub.pos, mb.pos), "same plastic synapses"
    assert int((ub.side == 1).sum()) == 27_939     # upstream's README numbers
    assert int((ub.side == -1).sum()) == 14_349
    disagree = int((ub.side != mb.side).sum())
    assert disagree == 12_606
    # restore: upstream's constructor called load(), which may have written
    # gains into fb.wdata
    ub.gain[:] = 1.0
    ub.apply()


def test_only_eligible_synapses_move_on_the_real_graph(real, mb):
    fb, mod, ann = real
    kc = np.flatnonzero(P.kenyon_cells(ann))
    fired = kc[:100]
    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.begin_episode(1)
    mb.observe(fired)
    eligible = (mb.trace > M.TRACE_EPS)
    assert eligible.sum() < len(mb.pos)
    n = mb.dopamine(-1, 1.0)
    assert n == int((eligible & (mb.side == -1)).sum()) > 0
    moved = mb.gain < 1.0
    assert np.array_equal(moved, eligible & (mb.side == -1))
    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.apply()


def test_applied_gains_reach_the_running_weights_on_the_real_graph(real, mb):
    fb, mod, ann = real
    base = fb.wdata[mb.pos].copy()
    mb.gain[:] = 0.5
    mb.apply()
    assert np.allclose(fb.wdata[mb.pos], base * 0.5)
    mb.gain[:] = 1.0
    mb.apply()
    assert np.allclose(fb.wdata[mb.pos], base)
