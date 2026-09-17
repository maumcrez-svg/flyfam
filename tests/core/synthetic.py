"""
A small synthetic connectome, written in the MaleCNS feather schema and built
through ``flytrade.graph.build`` — the same code path the real data takes.

Orientation is fixed by construction and follows the canonical mushroom body
(Aso et al. 2014 eLife 3:e04577):

* Kenyon cells are presynaptic to MBONs; that synapse is the plastic site.
* ``PAM_x`` innervates ``MBON_pam`` and ``PPL1_y`` innervates ``MBON_ppl1``.
* The MBON→DAN feedback is deliberately **crossed** — ``MBON_ppl1`` feeds back
  onto ``PAM_x`` and ``MBON_pam`` onto ``PPL1_y`` — so the transposed read
  upstream performs gives the *opposite* compartment assignment. A test that
  passes here cannot be passing by accident of a symmetric graph.

Synapse counts are chosen so one Kenyon cell crossing threshold drives its
MBON over threshold at full weight (40 synapses x 0.275 mV = 11.0 mV against a
7.0 mV gap) and fails to at the depression floor (0.25 x 11.0 = 2.75 mV).
That makes "the updated weights are actually used by the next simulation"
observable as a spike count, not just as a number in an array.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from flytrade import graph as G

# name, consensus_nt, class
NEURONS = [
    ("KC_a",      "acetylcholine", "Kenyon_Cell"),
    ("KC_b",      "acetylcholine", "Kenyon_Cell"),
    ("MBON_pam",  "acetylcholine", "MBON"),
    ("MBON_ppl1", "acetylcholine", "MBON"),
    ("PAM_x",     "dopamine",      "DAN"),
    ("PPL1_y",    "dopamine",      "DAN"),
    ("ORN_TEST",  "acetylcholine", "olfactory"),
    ("APL",       "gaba",          ""),
]

KC_TO_MBON = [
    ("KC_a", "MBON_pam", 40), ("KC_a", "MBON_ppl1", 40),
    ("KC_b", "MBON_pam", 40), ("KC_b", "MBON_ppl1", 40),
]
#: the edges the plasticity rule is supposed to read: DAN -> MBON
DAN_TO_MBON = [("PAM_x", "MBON_pam", 100), ("PPL1_y", "MBON_ppl1", 100)]
#: crossed MBON -> DAN feedback, so the transposed read answers differently
MBON_TO_DAN = [("MBON_ppl1", "PAM_x", 80), ("MBON_pam", "PPL1_y", 80)]
FILLER = [("ORN_TEST", "KC_a", 40), ("ORN_TEST", "KC_b", 40),
          ("APL", "KC_a", 5)]

BODY0 = 1000


def names() -> list[str]:
    return [n for n, _, _ in NEURONS]


def index_of(name: str) -> int:
    """Index in the built graph. ``bodies`` is sorted and assigned in order."""
    return names().index(name)


def write_feathers(tmpdir: Path, edges) -> Path:
    """Write the three input tables under the published file names."""
    d = Path(tmpdir)
    d.mkdir(parents=True, exist_ok=True)
    nm = names()
    bodies = np.arange(BODY0, BODY0 + len(nm), dtype=np.int64)
    n = len(nm)

    pd.DataFrame({
        "body_pre": np.array([bodies[nm.index(p)] for p, _, _ in edges], np.int64),
        "body_post": np.array([bodies[nm.index(q)] for _, q, _ in edges], np.int64),
        "weight": np.array([w for _, _, w in edges], np.int64),
    }).to_feather(d / G.FILES["weights"])

    pd.DataFrame({
        "bodyId": bodies,
        "type": nm,
        "flywireType": [None] * n,
        "instance": [None] * n,
        "superclass": ["cb_intrinsic"] * n,
        "subclass": [""] * n,
        "class": [c for _, _, c in NEURONS],
        "receptorType": [""] * n,
        "fruDsx": [""] * n,
        "somaSide": ["L"] * n,
        "rootSide": [""] * n,
        "somaNeuromere": [""] * n,
        "assignedOlHex1": [np.nan] * n,
        "assignedOlHex2": [np.nan] * n,
        "hemibrainType": [""] * n,
        "status": ["Traced"] * n,
        "statusLabel": ["Reviewed"] * n,
    }).to_feather(d / G.FILES["annotations"])

    pd.DataFrame({
        "body": bodies,
        "consensus_nt": [t for _, t, _ in NEURONS],
    }).to_feather(d / G.FILES["neurotransmitters"])
    return d


def build(tmpdir, *, dan_to_mbon=True, mbon_to_dan=True, min_syn_mod=1):
    """Build the three matrices for the synthetic graph; returns the out dir."""
    edges = list(KC_TO_MBON) + list(FILLER)
    if dan_to_mbon:
        edges += DAN_TO_MBON
    if mbon_to_dan:
        edges += MBON_TO_DAN
    data = write_feathers(Path(tmpdir) / "data", edges)
    out = Path(tmpdir) / "build"
    G.build(data, out, min_syn_mod=min_syn_mod, verbose=False)
    return out
