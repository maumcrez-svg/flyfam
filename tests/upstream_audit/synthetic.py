"""
Synthetic connectomes whose orientation is known by construction.

Nothing here rewrites upstream. The graphs are written in exactly the format
``build_graph.py`` emits (``build/graph.npz``) so that unmodified upstream
modules -- ``flysim.FlyBrain``, ``mushroom.MushroomBody`` -- can be imported
and run against them.

Two builders:

``write_graph_npz``   assembles ``graph.npz`` directly from an explicit edge
                      list.  Used to isolate *indexing* questions from the
                      neurotransmitter sign rule: it can put a non-zero weight
                      on a dopaminergic edge, which the real pipeline cannot.

``build_via_upstream`` writes synthetic ``.feather`` inputs and runs upstream's
                      own ``build_graph.main()`` over them (module constants
                      repointed at a tmp dir; no upstream line is changed).
                      Used to establish what the shipped pipeline actually
                      produces, sign rule included.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp

MV_PER_SYNAPSE = 0.275  # build_graph.py:21


@dataclass
class Neuron:
    name: str          # goes into `types`; mushroom.py matches ^KC / ^MBON / ^PAM / ^PPL1
    nt: str = "acetylcholine"
    superclass: str = ""
    subclass: str = ""
    receptor: str = ""
    fru: str = ""


@dataclass
class Graph:
    """An explicit pre->post edge list over named neurons."""
    neurons: list[Neuron]
    # (pre_name, post_name, n_synapses)
    edges: list[tuple[str, str, float]] = field(default_factory=list)

    def index(self, name: str) -> int:
        return [n.name for n in self.neurons].index(name)

    @property
    def n(self) -> int:
        return len(self.neurons)


SIGN = {  # build_graph.py:24-34, copied so a drift in either is visible
    "acetylcholine": +1.0,
    "gaba": -1.0,
    "glutamate": -1.0,
    "dopamine": 0.0,
    "octopamine": 0.0,
    "serotonin": 0.0,
    "histamine": -1.0,
    "unclear": 0.0,
    "unknown": 0.0,
}


def write_graph_npz(g: Graph, path, *, apply_sign_rule: bool = True,
                    drop_zero: bool = True):
    """
    Emit ``graph.npz`` with row = postsynaptic, col = presynaptic -- the
    convention build_graph.py:97-98 establishes.

    ``apply_sign_rule=False`` keeps modulatory (dopaminergic) edges at their
    raw synapse weight instead of zeroing them, so that a question about
    *indexing* can be asked without the sign rule deleting the evidence first.
    """
    n = g.n
    names = [x.name for x in g.neurons]
    nt = np.array([x.nt for x in g.neurons], dtype="U24")
    sign = np.array([SIGN.get(x.nt, 0.0) for x in g.neurons], dtype=np.float32)

    rows, cols, vals = [], [], []
    for pre, post, w in g.edges:
        c = names.index(pre)
        r = names.index(post)
        s = sign[c] if apply_sign_rule else (sign[c] if sign[c] != 0 else 1.0)
        rows.append(r)
        cols.append(c)
        vals.append(w * MV_PER_SYNAPSE * s)

    rows = np.asarray(rows, dtype=np.int32)
    cols = np.asarray(cols, dtype=np.int32)
    vals = np.asarray(vals, dtype=np.float32)
    if drop_zero:
        keep = vals != 0.0
        rows, cols, vals = rows[keep], cols[keep], vals[keep]

    W = sp.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=np.float32)
    W.sum_duplicates()

    np.savez_compressed(
        path,
        data=W.data, indices=W.indices, indptr=W.indptr, shape=W.shape,
        bodies=np.arange(1000, 1000 + n, dtype=np.int64),
        sign=sign,
        types=np.array(names, dtype=str),
        superclass=np.array([x.superclass for x in g.neurons], dtype=str),
        subclass=np.array([x.subclass for x in g.neurons], dtype=str),
        receptor=np.array([x.receptor for x in g.neurons], dtype=str),
        fru=np.array([x.fru for x in g.neurons], dtype=str),
        nt=nt,
    )
    return path


def build_via_upstream(g: Graph, tmpdir):
    """
    Run upstream ``build_graph.main()`` unmodified over synthetic feather
    inputs. Only the module-level DATA/BUILD constants are repointed.

    Returns the path to the produced graph.npz.
    """
    import pandas as pd
    import build_graph

    data = tmpdir / "data"
    build = tmpdir / "build"
    data.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)

    names = [x.name for x in g.neurons]
    bodies = np.arange(1000, 1000 + g.n, dtype=np.int64)

    pd.DataFrame({
        "body_pre": np.array([bodies[names.index(p)] for p, _, _ in g.edges],
                             dtype=np.int64),
        "body_post": np.array([bodies[names.index(q)] for _, q, _ in g.edges],
                              dtype=np.int64),
        "weight": np.array([w for _, _, w in g.edges], dtype=np.int64),
    }).to_feather(data / "connectome-weights.feather")

    pd.DataFrame({
        "bodyId": bodies,
        "type": names,
        "flywireType": [None] * g.n,
        "instance": [None] * g.n,
        "status": ["Traced"] * g.n,
        "statusLabel": ["Traced"] * g.n,
        "superclass": [x.superclass for x in g.neurons],
        "subclass": [x.subclass for x in g.neurons],
        "receptorType": [x.receptor for x in g.neurons],
        "fruDsx": [x.fru for x in g.neurons],
    }).to_feather(data / "body-annotations.feather")

    pd.DataFrame({
        "body": bodies,
        "consensus_nt": [x.nt for x in g.neurons],
    }).to_feather(data / "body-neurotransmitters.feather")

    old_data, old_build = build_graph.DATA, build_graph.BUILD
    try:
        build_graph.DATA = data
        build_graph.BUILD = build
        build_graph.main()
    finally:
        build_graph.DATA, build_graph.BUILD = old_data, old_build
    return build / "graph.npz"


# --- the mushroom-body test graph -------------------------------------------
#
# Orientation is fixed by construction and follows the canonical Drosophila
# mushroom-body arrangement (Aso et al. 2014, Owald et al. 2015, Hige et al.
# 2015):
#
#   * Kenyon cells are presynaptic to MBONs. That synapse is the plastic site.
#   * Appetitive (PAM) dopaminergic neurons innervate the compartments whose
#     MBONs drive AVOIDANCE; reward depresses KC->MBON there, so the fly stops
#     avoiding what paid.
#   * Aversive (PPL1) dopaminergic neurons innervate the compartments whose
#     MBONs drive APPROACH; punishment depresses KC->MBON there.
#
# So "the MBON a PAM neuron innervates" is the avoidance MBON. Upstream calls
# that set `reward_side` -- a naming choice about which DAN addresses it, not a
# claim about what it drives -- and `dopamine(+1)` depresses it. This module
# uses PAM_side / PPL1_side for the anatomical fact and leaves upstream's
# naming alone.

def mb_neurons() -> list[Neuron]:
    return [
        Neuron("KC_a"), Neuron("KC_b"),
        Neuron("MBON_approach", nt="glutamate"),
        Neuron("MBON_avoid", nt="acetylcholine"),
        Neuron("PAM_x", nt="dopamine"),
        Neuron("PPL1_y", nt="dopamine"),
        Neuron("DNa02"), Neuron("L1"), Neuron("APL", nt="gaba"),
    ]


KC_TO_MBON = [
    ("KC_a", "MBON_approach", 10.0),
    ("KC_a", "MBON_avoid", 10.0),
    ("KC_b", "MBON_approach", 10.0),
    ("KC_b", "MBON_avoid", 10.0),
]

# The only edges the docstring of mushroom.py says it reads: dopaminergic
# input onto MBONs. PAM -> the avoidance compartment, PPL1 -> the approach one.
DAN_TO_MBON = [
    ("PAM_x", "MBON_avoid", 100.0),
    ("PPL1_y", "MBON_approach", 100.0),
]

# Real MBON->DAN feedback, and it is crossed: the approach-driving
# MBON-gamma1pedc>alpha/beta feeds back onto PAM neurons, the avoidance side
# onto PPL1. Present only so that the two possible readings of the matrix give
# *different* answers rather than one of them giving nothing.
MBON_TO_DAN = [
    ("MBON_approach", "PAM_x", 80.0),
    ("MBON_avoid", "PPL1_y", 80.0),
]

FILLER = [
    ("L1", "KC_a", 5.0),
    ("L1", "KC_b", 5.0),
    ("MBON_approach", "DNa02", 7.0),
    ("MBON_avoid", "DNa02", 7.0),
    ("APL", "KC_a", 4.0),
]


def mb_graph(*, dan_to_mbon=True, mbon_to_dan=True) -> Graph:
    edges = list(KC_TO_MBON) + list(FILLER)
    if dan_to_mbon:
        edges += DAN_TO_MBON
    if mbon_to_dan:
        edges += MBON_TO_DAN
    return Graph(mb_neurons(), edges)
