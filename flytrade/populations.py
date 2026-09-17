"""
Population selectors over the MaleCNS v1.0 annotations.

Every selector here is a *documented* rule over annotation fields, not a
hand-written list of bodyIds. ``docs/POPULATIONS.md`` carries, for each one:
the selector, the count it produces on v1.0, and the owner's three-way split
between observed connectivity, literature interpretation, and our modelling
rule.

Two annotation fields matter and they do not always agree:

``class``      curated functional class: ``Kenyon_Cell``, ``MBON``, ``DAN``,
               ``ALPN``, ``olfactory``, ... Present for only 24,524 of the
               165,122 traced neurons, but where present it is the reviewed
               label.
``type``       the cell-type name, which is what upstream matches on with
               regexes like ``^KC`` / ``^MBON`` / ``^PAM`` / ``^PPL1``.

We select on ``class`` where it exists and on ``type`` where it does not, and
record every place the two disagree rather than silently preferring one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ------------------------------------------------------------------ loading


@dataclass
class Annotations:
    """Per-neuron annotation columns aligned to the graph's body index."""
    bodies: np.ndarray
    type: np.ndarray          # the same vector build_graph puts in `types`
    raw_type: np.ndarray      # the `type` column alone, no fallbacks
    flywire_type: np.ndarray
    instance: np.ndarray
    superclass: np.ndarray
    subclass: np.ndarray
    cls: np.ndarray           # the `class` column ("class" is a keyword)
    receptor: np.ndarray
    fru: np.ndarray
    soma_side: np.ndarray
    root_side: np.ndarray
    soma_neuromere: np.ndarray
    hex1: np.ndarray
    hex2: np.ndarray

    @classmethod
    def load(cls_, path) -> "Annotations":
        z = np.load(Path(path), allow_pickle=False)
        s = lambda k: z[k].astype(str)
        raw, fw, ins = s("type"), s("flywireType"), s("instance")
        merged = np.where(raw != "", raw,
                          np.where(fw != "", fw, np.where(ins != "", ins, "")))
        return cls_(
            bodies=z["bodies"], type=merged, raw_type=raw, flywire_type=fw,
            instance=ins, superclass=s("superclass"), subclass=s("subclass"),
            cls=s("class"), receptor=s("receptorType"), fru=s("fruDsx"),
            soma_side=s("somaSide"), root_side=s("rootSide"),
            soma_neuromere=s("somaNeuromere"),
            hex1=z["assignedOlHex1"], hex2=z["assignedOlHex2"],
        )

    @property
    def n(self) -> int:
        return len(self.bodies)


def _rx(values: np.ndarray, pattern: str, full: bool = False) -> np.ndarray:
    r = re.compile(pattern)
    f = r.fullmatch if full else r.match
    return np.array([bool(f(v)) for v in values], dtype=bool)


# ---------------------------------------------------------------- selectors
#
# Each entry is (name, docstring-ish description, callable -> bool mask).
# Keep them small and readable: they are the thing a reviewer checks.

def kenyon_cells(a: Annotations) -> np.ndarray:
    """class == Kenyon_Cell. Equivalent on v1.0 to type ^KC."""
    return a.cls == "Kenyon_Cell"


def kc_subtypes(a: Annotations) -> dict[str, np.ndarray]:
    """KCs split by their type name (KCg-m, KCab-s, KCa'b'-ap1, ...)."""
    m = kenyon_cells(a)
    out = {}
    for t in sorted(set(a.type[m])):
        out[t] = np.flatnonzero(m & (a.type == t))
    return out


def mbons(a: Annotations) -> np.ndarray:
    """class == MBON. Includes the four ``MBONxx-like`` types."""
    return a.cls == "MBON"


def mbon_canonical(a: Annotations) -> np.ndarray:
    """MBONs with a canonical ``MBON<nn>`` name, excluding ``-like``."""
    return mbons(a) & _rx(a.type, r"MBON\d+$", full=True)


#: The MBON types the mushroom-body valence literature attributes a behavioural
#: direction to: MBON01-MBON15, the set Aso, Hattori, Yu et al. 2014 (eLife
#: 3:e04577) gives a compartment for and Aso, Sitaraman, Ichinose et al. 2014
#: (eLife 3:e04580) measures an optogenetic valence for. Numbering is the
#: hemibrain numbering, which MaleCNS v1.0 is *assumed* to share — see
#: ``docs/POPULATIONS.md`` ambiguity 1. Higher-numbered MBONs and the three
#: ``-like`` types are deliberately outside it.
ATTRIBUTED_MBON_RANGE = (1, 15)


def mbon_attributed(a: Annotations, rng=ATTRIBUTED_MBON_RANGE) -> np.ndarray:
    """MBONs with a literature-attributed valence: ``MBON01``..``MBON15``.

    A *naming* rule over a literature range, not a measurement of this
    dataset. Excludes every ``-like`` type by requiring a full match. Used by
    the action decoder, which must not guess a valence for an MBON nobody has
    attributed one to.
    """
    lo, hi = rng
    names = {f"MBON{n:02d}" for n in range(lo, hi + 1)}
    return mbons(a) & np.isin(a.type, sorted(names))


def pam(a: Annotations) -> np.ndarray:
    """type ^PAM. All 316 are class DAN and consensus_nt dopamine."""
    return _rx(a.type, r"PAM")


def ppl1(a: Annotations) -> np.ndarray:
    """type ^PPL1, i.e. PPL101..PPL108. Excludes PPL2xx by construction."""
    return _rx(a.type, r"PPL1")


def ppl2(a: Annotations) -> np.ndarray:
    """type ^PPL2. Recorded because ^PPL1 silently excludes it."""
    return _rx(a.type, r"PPL2")


def dans(a: Annotations) -> np.ndarray:
    """class == DAN — the curated dopaminergic-neuron class."""
    return a.cls == "DAN"


def apl(a: Annotations) -> np.ndarray:
    """type == APL. The single giant GABAergic feedback neuron per hemisphere."""
    return a.type == "APL"


def orns(a: Annotations) -> np.ndarray:
    """class == olfactory AND type ^ORN_ — olfactory receptor neurons."""
    return (a.cls == "olfactory") & _rx(a.type, r"ORN_")


def orn_glomeruli(a: Annotations) -> dict[str, np.ndarray]:
    """ORNs grouped by the glomerulus in their type name (ORN_DA1 -> DA1)."""
    m = orns(a)
    out = {}
    for t in sorted(set(a.type[m])):
        out[t[len("ORN_"):]] = np.flatnonzero(m & (a.type == t))
    return out


#: multiglomerular / ambiguous antennal-lobe projection neurons, excluded from
#: the uniglomerular set. ``M_``/``MZ_`` is the dataset's own prefix for
#: multiglomerular PNs; ``+`` in a name lists several glomeruli; ``CB####``
#: names carry no glomerulus at all.
_MULTIGLOM = re.compile(r"^(M_|MZ_|CB\d)")


def upns(a: Annotations) -> np.ndarray:
    """Uniglomerular antennal-lobe projection neurons.

    class == ALPN, minus every name that is explicitly multiglomerular
    (``M_``/``MZ_`` prefix), lists more than one glomerulus (``+``), or has no
    glomerulus in its name at all (``CB####``).
    """
    m = a.cls == "ALPN"
    keep = np.array([not _MULTIGLOM.match(t) and "+" not in t
                     for t in a.type], dtype=bool)
    return m & keep


def upn_glomeruli(a: Annotations) -> dict[str, np.ndarray]:
    """Uniglomerular PNs grouped by glomerulus (``DA1_lPN`` -> ``DA1``)."""
    m = upns(a)
    out: dict[str, list[int]] = {}
    for i in np.flatnonzero(m):
        out.setdefault(a.type[i].split("_", 1)[0], []).append(int(i))
    return {k: np.asarray(v, dtype=np.int64) for k, v in sorted(out.items())}


def by_type(a: Annotations, name: str, side: str | None = None) -> np.ndarray:
    """Exact type-name match, optionally restricted to a soma side."""
    m = a.type == name
    if side is not None:
        m = m & (a.soma_side == side)
    return m


# ------------------------------------------------ DAN -> MBON compartments

def dan_input_table(mod, a: Annotations, mbon_idx: np.ndarray,
                    pam_idx: np.ndarray, ppl1_idx: np.ndarray):
    """For each MBON: dopaminergic synapses received from PAM and from PPL1.

    This is the read upstream's docstring describes and its code does not do.
    ``mod`` is a :class:`flytrade.graph.ModulatoryGraph`; the convention is
    ``[post, pre]`` throughout, so ``mod.input_weight(mbon, pam)`` is
    "synapses each MBON RECEIVES from PAM neurons".
    """
    pam_in = mod.input_weight(mbon_idx, pam_idx)
    ppl_in = mod.input_weight(mbon_idx, ppl1_idx)
    return pam_in, ppl_in
