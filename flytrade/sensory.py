"""
Olfactory stimuli for Phase 0.5.

This is **not** the SensoryEncoder SPEC asks for — there is no market
measurement anywhere in this wave. It is the minimum needed to ask whether a
stimulus reaches the mushroom body and whether pairing it with reinforcement
changes the later response.

The rule that picks the two odours is documented in
``experiments/conditioning/PROTOCOL.md`` §3 and fixed there before any
conditioning result existed. It is reproduced in code rather than hard-coded
as a list of glomerulus names so that the selection stays a rule.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import populations as P

VERSION = "flytrade-odour-1"

#: Pheromone channels whose projection neurons are biased toward the lateral
#: horn rather than the mushroom-body calyx (Jefferis, Potter, Chan et al.
#: 2007, Cell 128:1187-1203). Excluded from the candidate pool.
PHEROMONE_GLOMERULI = ("DA1", "VA1v", "VA1d", "DL3")

#: How many glomeruli go into each odour.
N_PER_ODOUR = 5

#: Per-ORN drive, Hz. Within the range of measured Drosophila ORN odour
#: responses (de Bruyne, Foster & Carlson 2001, Neuron 30:537-552).
DRIVE_HZ = 150.0

#: Uniform synaptic-efficacy multiplier over every cell type. See PROTOCOL.md
#: §2 for the selection rule and the sweep that produced it. The upstream
#: default (no gains, i.e. 1.0) saturates the whole connectome.
GLOBAL_GAIN = 0.10

#: Simulation steps per presentation; 100 x 0.2 ms = 20 ms of brain time.
STEPS = 100


@dataclass(frozen=True)
class Odour:
    name: str
    glomeruli: tuple[str, ...]
    orns: np.ndarray

    def drive(self, hz: float = DRIVE_HZ) -> dict:
        return {tuple(int(i) for i in self.orns): float(hz)}

    def __len__(self):
        return len(self.orns)


def candidate_glomeruli(a: P.Annotations) -> list[str]:
    """Glomeruli with both ORNs and uniglomerular PNs, minus the pheromone
    channels. Sorted, so the result does not depend on dict ordering."""
    og, ug = P.orn_glomeruli(a), P.upn_glomeruli(a)
    return [g for g in sorted(set(og) & set(ug))
            if g not in PHEROMONE_GLOMERULI]


def odour_pair(a: P.Annotations) -> tuple[Odour, Odour]:
    """The two test odours, by the rule pre-registered in PROTOCOL.md §3.

    Take the ``2 * N_PER_ODOUR`` candidates with the most uniglomerular PNs
    (ties broken alphabetically) and snake-draft them into two sets, which
    balances uPN count between the two odours. Nothing downstream of the
    sensory path enters this choice.
    """
    og, ug = P.orn_glomeruli(a), P.upn_glomeruli(a)
    ranked = sorted(candidate_glomeruli(a),
                    key=lambda g: (-len(ug[g]), g))[:2 * N_PER_ODOUR]
    ga, gb = [], []
    for i, g in enumerate(ranked):
        (ga if (i % 4) in (0, 3) else gb).append(g)
    return (Odour("A", tuple(ga), np.concatenate([og[g] for g in ga])),
            Odour("B", tuple(gb), np.concatenate([og[g] for g in gb])))


def uniform_gains(fb, value: float = GLOBAL_GAIN) -> np.ndarray:
    """One synaptic-efficacy multiplier, applied to every cell type alike."""
    return np.full(fb.n_types, float(value), dtype=np.float32)
