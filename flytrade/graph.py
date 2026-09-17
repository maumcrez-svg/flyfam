"""
Build the three connectivity matrices Flytrade needs from the MaleCNS v1.0
flat-connectome tables.

Upstream's ``build_graph.py`` produces exactly one matrix: fast synaptic weight
in mV, with the neurotransmitter sign already folded in and every zero-signed
edge deleted. That single step destroys the dopaminergic wiring (dopamine is
signed 0.0, and ``keep = v != 0.0`` drops the edge), which is why upstream's
plasticity rule cannot read DAN->MBON input and reads MBON->DAN feedback
instead. See ``docs/UPSTREAM_NOTES.md`` §2.

We therefore keep the anatomy first and sign it afterwards, and we keep the
modulatory wiring in its own matrix:

  ANATOMICAL  A[post, pre] = synapse count, non-negative, no sign applied.
              Every traced-neuron -> traced-neuron pair. This is the
              measurement; everything else is derived from it.

  FAST        W[post, pre] = A * 0.275 mV * sign(nt of pre), edges with
              sign 0 dropped, pairs with < MIN_SYN_FAST synapses dropped.
              Byte-identical in format to upstream's ``graph.npz`` so upstream
              code can still be run over it for comparison.

  MODULATORY  D[post, pre] = synapse count, non-negative, restricted to
              presynaptic neurons whose consensus neurotransmitter is
              dopamine. Never converted into fast excitation: it is only ever
              read as "which compartment does this DAN address, and how
              strongly".

All three use the SAME neuron index (``bodies``, sorted ascending) and the SAME
[post, pre] convention as ``build_graph.py:97-98``.

Robustness note: upstream sizes a lookup table from ``max(pre, post)`` and then
indexes it with every traced bodyId (``build_graph.py:75-76``), which raises
IndexError if a traced neuron has no kept edge and the highest bodyId.  We use
``searchsorted`` against the sorted body index instead, which has no such
bound.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

# ---------------------------------------------------------------- constants

MV_PER_SYNAPSE = 0.275   # Shiu et al. 2024 (Nature); same value upstream uses
MIN_SYN_FAST = 3         # upstream's build_graph.py:22 filter for the fast layer
MIN_SYN_MOD = 1          # the modulatory layer's OWN threshold, deliberately not
                         # inherited from the fast layer. Measured decision, see
                         # docs/ARCHITECTURE.md "Modulatory threshold": the fast
                         # layer's >=3 cut exists to suppress reconstruction noise
                         # in a voltage sum; the modulatory layer computes
                         # compartment membership, not voltage, and the >=3 cut
                         # discards 77.6% of dopaminergic edges (241,702 -> 54,171)
                         # and leaves 2 of 97 MBONs unclassifiable. 94 of 97 MBONs
                         # get the same side at either threshold; the 3 that move
                         # are flagged ambiguous by classify_compartments().

SIGN = {
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

MODULATORY_NT = ("dopamine", "octopamine", "serotonin")

SCHEMA_VERSION = "flytrade-graph-1"

FILES = {
    "annotations": "body-annotations-male-cns-v1.0-minconf-0.5.feather",
    "neurotransmitters": "body-neurotransmitters-male-cns-v1.0.feather",
    "weights": "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
}

# Annotation columns we carry per neuron, aligned to the body index.
ANN_COLUMNS = (
    "type", "flywireType", "instance", "superclass", "subclass", "class",
    "receptorType", "fruDsx", "somaSide", "rootSide", "somaNeuromere",
    "assignedOlHex1", "assignedOlHex2", "hemibrainType", "status",
    "statusLabel",
)


# ------------------------------------------------------------------ helpers

def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _index_of(bodies: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Position of each id in the sorted ``bodies``, or -1 when absent.

    Replaces upstream's max-sized boolean lookup table, which is both huge
    (max bodyId is ~1.57e9) and can raise IndexError.
    """
    pos = np.searchsorted(bodies, ids)
    np.clip(pos, 0, len(bodies) - 1, out=pos)
    ok = bodies[pos] == ids
    return np.where(ok, pos, -1).astype(np.int32)


# ------------------------------------------------------------------- report

@dataclass
class BuildReport:
    neurons: int = 0
    weight_rows_on_disk: int = 0
    anatomical_edges: int = 0
    anatomical_synapses: int = 0
    anatomical_edges_min1: int = 0
    fast_edges: int = 0
    fast_excitatory: int = 0
    fast_inhibitory: int = 0
    dropped_by_sign: int = 0
    dan_outgoing_edges_dropped_by_upstream_rule: int = 0
    modulatory_edges: int = 0
    modulatory_edges_min1: int = 0
    modulatory_presynaptic_neurons: int = 0
    mod_threshold_sweep: dict = field(default_factory=dict)
    nt_counts: dict = field(default_factory=dict)
    graph_sha256: str = ""
    graph_mod_sha256: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# -------------------------------------------------------------------- build

def load_annotations(data_dir: Path) -> pd.DataFrame:
    cols = list(dict.fromkeys(("bodyId",) + ANN_COLUMNS))
    ann = pd.read_feather(data_dir / FILES["annotations"], columns=cols)
    return ann.drop_duplicates(subset=["bodyId"])


def traced_bodies(ann: pd.DataFrame) -> np.ndarray:
    """The 165,122 reconstructed neurons: upstream's own selection rule."""
    sel = (ann["status"] == "Traced") & (ann["statusLabel"] != "Glia")
    return np.sort(ann.loc[sel, "bodyId"].unique()).astype(np.int64)


def load_nt(data_dir: Path, bodies: np.ndarray) -> np.ndarray:
    nt = pd.read_feather(data_dir / FILES["neurotransmitters"],
                         columns=["body", "consensus_nt"])
    nt = nt.dropna(subset=["body"]).drop_duplicates(subset=["body"])
    m = nt.set_index("body")["consensus_nt"]
    s = m.reindex(bodies).fillna("unknown")
    return s.str.lower().to_numpy().astype("U24")


def build(data_dir: Path, out_dir: Path, *,
          min_syn_fast: int = MIN_SYN_FAST,
          min_syn_mod: int = MIN_SYN_MOD,
          verbose: bool = True) -> BuildReport:
    """Write ``graph.npz`` (fast), ``graph_mod.npz`` (modulatory),
    ``graph_anat.npz`` (anatomy) and ``annotations.npz`` into ``out_dir``."""
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = BuildReport()

    def say(*a):
        if verbose:
            print(*a, flush=True)

    ann = load_annotations(data_dir)
    bodies = traced_bodies(ann)
    n = len(bodies)
    rep.neurons = n
    say(f"traced neurons: {n:,}")

    nt_str = load_nt(data_dir, bodies)
    sign = np.array([SIGN.get(s, 0.0) for s in nt_str], dtype=np.float32)
    vals, cnts = np.unique(nt_str, return_counts=True)
    rep.nt_counts = {str(v): int(c) for v, c in zip(vals, cnts)}

    ann_i = ann.set_index("bodyId").reindex(bodies)

    def col(name, dtype=str):
        if name not in ann_i.columns:
            return np.full(n, "", dtype=str)
        return ann_i[name].fillna("").to_numpy().astype(dtype)

    types = ann_i["type"].fillna(ann_i["flywireType"]).fillna(
        ann_i["instance"]).fillna("").to_numpy().astype(str)

    # ---- anatomy -------------------------------------------------------
    import pyarrow.feather as pf

    say("loading weights ...")
    tbl = pf.read_table(data_dir / FILES["weights"])
    rep.weight_rows_on_disk = tbl.num_rows
    say(f"  {tbl.num_rows:,} pre->post pairs on disk")
    pre_b = tbl.column("body_pre").to_numpy()
    post_b = tbl.column("body_post").to_numpy()
    wt = tbl.column("weight").to_numpy()
    del tbl

    pre_i = _index_of(bodies, pre_b)
    del pre_b
    post_i = _index_of(bodies, post_b)
    del post_b
    ok = (pre_i >= 0) & (post_i >= 0)
    pre_i, post_i = pre_i[ok], post_i[ok]
    wt = wt[ok].astype(np.int32)
    del ok
    rep.anatomical_edges_min1 = int(len(wt))
    say(f"  {len(wt):,} neuron->neuron edges at >=1 synapse")

    # the anatomical layer we keep is thresholded at the same MIN_SYN as the
    # fast layer; the sub-threshold edges stay visible through
    # anatomical_edges_min1 and through evaluate_mod_threshold().
    keep_anat = wt >= min_syn_fast
    a_pre, a_post, a_w = pre_i[keep_anat], post_i[keep_anat], wt[keep_anat]
    rep.anatomical_edges = int(len(a_w))
    rep.anatomical_synapses = int(a_w.sum())
    say(f"  {len(a_w):,} edges at >={min_syn_fast} synapses, "
        f"{int(a_w.sum()):,} synapses")

    A = sp.csr_matrix((a_w.astype(np.float32), (a_post, a_pre)),
                      shape=(n, n), dtype=np.float32)
    A.sum_duplicates()

    # ---- fast layer (upstream's exact output format) --------------------
    v = a_w.astype(np.float32) * MV_PER_SYNAPSE * sign[a_pre]
    keep = v != 0.0
    rep.dropped_by_sign = int((~keep).sum())
    W = sp.csr_matrix((v[keep], (a_post[keep], a_pre[keep])),
                      shape=(n, n), dtype=np.float32)
    W.sum_duplicates()
    rep.fast_edges = int(W.nnz)
    rep.fast_excitatory = int((W.data > 0).sum())
    rep.fast_inhibitory = int((W.data < 0).sum())
    say(f"  fast: {W.nnz:,} edges "
        f"(+{rep.fast_excitatory:,} / -{rep.fast_inhibitory:,}), "
        f"{rep.dropped_by_sign:,} dropped by the sign rule")

    is_dop = np.zeros(n, dtype=bool)
    is_dop[nt_str == "dopamine"] = True
    rep.dan_outgoing_edges_dropped_by_upstream_rule = int(is_dop[a_pre].sum())

    # ---- modulatory layer ----------------------------------------------
    dop_all = is_dop[pre_i]
    rep.modulatory_edges_min1 = int(dop_all.sum())
    # threshold sweep, measured in the same pass so the choice of MIN_SYN_MOD
    # is evidence rather than an inherited default
    rep.mod_threshold_sweep = {
        str(t): {
            "edges": int((dop_all & (wt >= t)).sum()),
            "synapses": int(wt[dop_all & (wt >= t)].sum()),
            "pre_neurons": int(len(np.unique(pre_i[dop_all & (wt >= t)]))),
            "post_neurons": int(len(np.unique(post_i[dop_all & (wt >= t)]))),
        }
        for t in (1, 2, 3, 5)
    }
    keep_mod = dop_all & (wt >= min_syn_mod)
    m_pre, m_post, m_w = pre_i[keep_mod], post_i[keep_mod], wt[keep_mod]
    rep.modulatory_edges = int(len(m_w))
    rep.modulatory_presynaptic_neurons = int(len(np.unique(m_pre)))
    say(f"  modulatory (dopamine pre): {len(m_w):,} edges at "
        f">={min_syn_mod} synapses, {rep.modulatory_edges_min1:,} at >=1")

    D = sp.csr_matrix((m_w.astype(np.float32), (m_post, m_pre)),
                      shape=(n, n), dtype=np.float32)
    D.sum_duplicates()

    del pre_i, post_i, wt, dop_all, keep_mod, keep_anat, v, keep

    # ---- write ----------------------------------------------------------
    # graph.npz keeps upstream's key set exactly, so flysim.FlyBrain loads it.
    np.savez_compressed(
        out_dir / "graph.npz",
        data=W.data, indices=W.indices, indptr=W.indptr, shape=W.shape,
        bodies=bodies, sign=sign, types=types,
        superclass=col("superclass"), subclass=col("subclass"),
        receptor=col("receptorType"), fru=col("fruDsx"), nt=nt_str,
    )
    np.savez_compressed(
        out_dir / "graph_mod.npz",
        data=D.data, indices=D.indices, indptr=D.indptr, shape=D.shape,
        bodies=bodies, nt=nt_str,
        min_syn=np.int32(min_syn_mod), schema=np.str_(SCHEMA_VERSION),
    )
    np.savez_compressed(
        out_dir / "graph_anat.npz",
        data=A.data, indices=A.indices, indptr=A.indptr, shape=A.shape,
        bodies=bodies, min_syn=np.int32(min_syn_fast),
        schema=np.str_(SCHEMA_VERSION),
    )
    np.savez_compressed(
        out_dir / "annotations.npz",
        bodies=bodies,
        **{c: col(c) for c in ANN_COLUMNS if c not in
           ("assignedOlHex1", "assignedOlHex2")},
        assignedOlHex1=ann_i["assignedOlHex1"].to_numpy().astype(np.float64),
        assignedOlHex2=ann_i["assignedOlHex2"].to_numpy().astype(np.float64),
    )

    rep.graph_sha256 = sha256_file(out_dir / "graph.npz")
    rep.graph_mod_sha256 = sha256_file(out_dir / "graph_mod.npz")
    (out_dir / "build_report.json").write_text(
        json.dumps(rep.as_dict(), indent=2, sort_keys=True))
    say(f"wrote {out_dir}/graph.npz, graph_mod.npz, graph_anat.npz, "
        f"annotations.npz")
    return rep


# ------------------------------------------------- modulatory-layer loading

class ModulatoryGraph:
    """``D[post, pre]`` — unsigned dopaminergic synapse counts.

    Loaded alongside a ``flysim.FlyBrain``; the two share a body index and the
    constructor checks it.
    """

    def __init__(self, path, bodies=None):
        z = np.load(path, allow_pickle=False)
        self.D = sp.csr_matrix(
            (z["data"], z["indices"], z["indptr"]), shape=tuple(z["shape"]))
        self.bodies = z["bodies"]
        self.nt = z["nt"].astype(str)
        self.min_syn = int(z["min_syn"])
        if bodies is not None and not np.array_equal(self.bodies, bodies):
            raise ValueError(
                "modulatory graph body index does not match the fast graph")

    @property
    def n(self):
        return self.D.shape[0]

    def input_weight(self, post, pre):
        """Total dopaminergic synapse count from ``pre`` onto each of ``post``.

        [post, pre] throughout: ``D[post][:, pre].sum(axis=1)`` is, for every
        neuron in ``post``, the number of synapses it RECEIVES from the
        neurons in ``pre``. One value per entry of ``post``.
        """
        post = np.asarray(post, dtype=np.int64)
        pre = np.asarray(pre, dtype=np.int64)
        if not len(post) or not len(pre):
            return np.zeros(len(post), dtype=np.float64)
        return np.asarray(self.D[post][:, pre].sum(axis=1)).ravel()


def evaluate_mod_threshold(data_dir: Path, bodies: np.ndarray,
                           nt_str: np.ndarray, thresholds=(1, 3)) -> dict:
    """Edge counts for the modulatory layer at several synapse thresholds.

    Kept separate from ``build`` so the threshold choice is a measurement, not
    a default inherited from the fast layer.
    """
    import pyarrow.feather as pf

    tbl = pf.read_table(data_dir / FILES["weights"])
    pre_i = _index_of(bodies, tbl.column("body_pre").to_numpy())
    post_i = _index_of(bodies, tbl.column("body_post").to_numpy())
    wt = tbl.column("weight").to_numpy().astype(np.int32)
    del tbl
    ok = (pre_i >= 0) & (post_i >= 0)
    pre_i, post_i, wt = pre_i[ok], post_i[ok], wt[ok]
    is_dop = (nt_str == "dopamine")
    dop = is_dop[pre_i]
    out = {}
    for t in thresholds:
        sel = dop & (wt >= t)
        out[t] = {
            "edges": int(sel.sum()),
            "synapses": int(wt[sel].sum()),
            "pre_neurons": int(len(np.unique(pre_i[sel]))),
            "post_neurons": int(len(np.unique(post_i[sel]))),
        }
    return out
