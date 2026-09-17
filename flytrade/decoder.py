"""
The action decoder — fixed, documented, pre-registered.

``docs/DECODER.md`` is this module's specification and the two are committed
together, alone, before any execution or PnL code exists. That commit is the
evidence that the readout, its sign, its aggregation, its threshold and its tie
rule were fixed before any trading outcome had been seen, exactly as
``experiments/conditioning/PROTOCOL.md`` was fixed before the conditioning run.
Nothing here may be touched after a PnL has been observed.

What this is not: there is no strategy, no classifier, no learned policy and no
model of a market anywhere in this file. The decoder compares two measured
firing rates against a threshold in units of their own measurement noise. Every
market-dependent quantity reached it through the sensory path.

## The readout

Two populations, both **measured** from the corrected DAN -> MBON compartment
map in ``flytrade/mushroom.py`` and both restricted to the MBONs the valence
literature attributes a behavioural direction to
(``populations.mbon_attributed``, MBON01-MBON15):

* ``avoid``   — 29 neurons, PAM-innervated (MBON01-MBON10 on this dataset)
* ``approach`` — 16 neurons, PPL1-innervated (MBON11-MBON15)

The 52 remaining MBONs are **excluded**, not guessed: MBON16-MBON35 and the
three ``-like`` types have no compartment-plus-valence attribution we are
willing to stand behind (``docs/POPULATIONS.md`` ambiguities 1 and 5).

## The three things that must not be conflated

a) *modulation compartment* — which dopaminergic cluster innervates the MBON.
   Measured here, from ``graph_mod.npz``.
b) *literature-attributed valence* — what activating that MBON is reported to
   make a fly do. **Attributed, not measured by us.**
c) *our action-mapping convention* — the arbitrary, declared step from (b) to
   BUY/SELL/WAIT. Ours, and labelled as ours.

The table is in ``docs/DECODER.md``. The direction is the one the literature
reports and it is the *opposite* of the naive reading the amendment warns
against: PAM-innervated ("reward") compartments hold avoidance-promoting MBONs
and PPL1-innervated ("punishment") compartments hold approach-promoting ones.

## The rule

    V_raw = mean rate(approach) - mean rate(avoid)          [Hz]
    V     = V_raw - BASELINE_HZ                             [Hz]

    INVALID_STATE  if the Kenyon-cell active fraction exceeds MAX_KC_FRACTION,
                   or any read neuron sits within 5% of the refractory ceiling
    NO_RESPONSE    if both populations are silent
    BUY            if V >  +THETA_HZ
    SELL           if V <  -THETA_HZ
    WAIT           otherwise

``BASELINE_HZ`` and ``THETA_HZ`` are measured quantities with a stated
provenance, not tuned numbers; see the constants below. Selection across
candidates is ``argmax V``, ties to the lowest stable id
(``flytrade/runner.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from . import populations as P

VERSION = "flytrade-action-1"

#: name of the approach-promoting readout population (PPL1-innervated)
APPROACH = "approach"
#: name of the avoidance-promoting readout population (PAM-innervated)
AVOID = "avoid"

#: Mean of ``V_raw`` at the neutral reference stimulus (every feature at its
#: own trailing median), gain 0.10, unlearned weights, declared operating
#: range, over the 8 declared seeds. Measured by
#: ``experiments/phase_one/encoder_range.py`` Part C and recorded in
#: ``encoder_range.json`` as ``neutral_reference.attributed_diff_hz_mean``.
#: The fly's readout is not balanced at rest and this is the offset, not a
#: tuning knob.
BASELINE_HZ = -2.303340517241379

#: Seed-to-seed SD of ``V_raw`` at that same reference, same source
#: (``attributed_diff_hz_sd``). This is the unit the WAIT margin is in.
BASELINE_SD_HZ = 3.241438214716715

#: WAIT margin, in units of BASELINE_SD_HZ (Fable addendum 4). One SD: a
#: readout that could plausibly be produced by seed noise alone is not a
#: decision.
THETA_SD = 1.0
THETA_HZ = THETA_SD * BASELINE_SD_HZ

#: Kenyon-cell recruitment above this is the saturated regime PROTOCOL.md §2
#: rules out; a readout taken there is INVALID_STATE, not a decision.
MAX_KC_FRACTION = 0.25

#: refractory ceiling, 1000 / 2.2 ms; within 5% of it the rate is pinned
REFRACTORY_CEILING_HZ = 1000.0 / 2.2
SATURATED_HZ = 0.95 * REFRACTORY_CEILING_HZ


class Action(str, Enum):
    """What a decoder may emit. ``NO_RESPONSE`` is not a decision."""

    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    #: the readout was silent or unusable — recorded as such, never as a choice
    NO_RESPONSE = "NO_RESPONSE"

    @property
    def is_decision(self) -> bool:
        """False for ``NO_RESPONSE``: an absence of activity is not a choice."""
        return self is not Action.NO_RESPONSE


class ReadoutStatus(str, Enum):
    """The four cases amendment §3 requires to stay distinguishable.

    ``Action`` gains no members for these (Fable addendum 4): a record carries
    a status alongside its action, so "the fly decoded WAIT" is never confused
    with "there was nothing to decode from" or "the execution policy said no".
    """

    #: a real readout, decoded into BUY / SELL / WAIT
    VALID = "VALID"
    #: both readout populations silent — nothing was measured
    NO_RESPONSE = "NO_RESPONSE"
    #: saturated or otherwise outside the declared operating range
    INVALID_STATE = "INVALID_STATE"
    #: the decoder produced a valid action and the execution policy refused it
    POLICY_REJECT = "POLICY_REJECT"


@dataclass(frozen=True)
class Decision:
    """One decoded readout. Carries the numbers it was decided from."""

    action: Action
    status: ReadoutStatus
    valence_hz: float          # V, centred
    raw_valence_hz: float      # V_raw, uncentred
    approach_hz: float
    avoid_hz: float
    kc_fraction: float
    max_rate_hz: float
    theta_hz: float
    decoder_version: str = VERSION
    reason: str = ""

    @property
    def is_decision(self) -> bool:
        return self.status is ReadoutStatus.VALID and self.action.is_decision

    def as_dict(self) -> dict:
        return {
            "action": self.action.value, "readout_status": self.status.value,
            "valence_hz": round(self.valence_hz, 6),
            "raw_valence_hz": round(self.raw_valence_hz, 6),
            "approach_hz": round(self.approach_hz, 6),
            "avoid_hz": round(self.avoid_hz, 6),
            "kc_fraction": round(self.kc_fraction, 6),
            "max_rate_hz": round(self.max_rate_hz, 6),
            "theta_hz": round(self.theta_hz, 6),
            "decoder_version": self.decoder_version,
            "reason": self.reason,
        }


def readout_populations(ann: P.Annotations, compartments) -> dict[str, np.ndarray]:
    """The two readout populations, from the measured compartment map.

    ``compartments`` is a :class:`flytrade.mushroom.Compartments`. An MBON that
    the compartment map leaves unclassified, or that it flags as resting on
    thin or near-tied dopaminergic evidence, is dropped here as well: a
    decoder must not read a neuron whose compartment is a coin toss.
    """
    attributed = set(int(i) for i in np.flatnonzero(P.mbon_attributed(ann)))
    ambiguous = set(int(i) for i in compartments.ambiguous)
    keep = attributed - ambiguous

    def take(side):
        return np.array(sorted(int(i) for i in side if int(i) in keep),
                        dtype=np.int64)

    return {AVOID: take(compartments.pam_side),
            APPROACH: take(compartments.ppl1_side)}


class ActionDecoder:
    """The fixed decoder. No state, no learning, no market knowledge."""

    version = VERSION

    def __init__(self, *, baseline_hz: float = BASELINE_HZ,
                 theta_hz: float = THETA_HZ,
                 max_kc_fraction: float = MAX_KC_FRACTION,
                 saturated_hz: float = SATURATED_HZ):
        self.baseline_hz = float(baseline_hz)
        self.theta_hz = float(theta_hz)
        self.max_kc_fraction = float(max_kc_fraction)
        self.saturated_hz = float(saturated_hz)

    def decode_rates(self, approach_hz: float, avoid_hz: float, *,
                     kc_fraction: float = 0.0,
                     max_rate_hz: float = 0.0) -> Decision:
        raw = float(approach_hz) - float(avoid_hz)
        v = raw - self.baseline_hz
        common = dict(valence_hz=v, raw_valence_hz=raw,
                      approach_hz=float(approach_hz), avoid_hz=float(avoid_hz),
                      kc_fraction=float(kc_fraction),
                      max_rate_hz=float(max_rate_hz), theta_hz=self.theta_hz)

        if kc_fraction > self.max_kc_fraction:
            return Decision(action=Action.NO_RESPONSE,
                            status=ReadoutStatus.INVALID_STATE,
                            reason=f"Kenyon-cell active fraction "
                                   f"{kc_fraction:.4f} > {self.max_kc_fraction}",
                            **common)
        if max_rate_hz >= self.saturated_hz:
            return Decision(action=Action.NO_RESPONSE,
                            status=ReadoutStatus.INVALID_STATE,
                            reason=f"a read neuron at {max_rate_hz:.1f} Hz is "
                                   f"pinned against the refractory ceiling",
                            **common)
        if approach_hz == 0.0 and avoid_hz == 0.0:
            return Decision(action=Action.NO_RESPONSE,
                            status=ReadoutStatus.NO_RESPONSE,
                            reason="both readout populations silent",
                            **common)
        if v > self.theta_hz:
            return Decision(action=Action.BUY, status=ReadoutStatus.VALID,
                            reason=f"V {v:+.3f} Hz > +theta {self.theta_hz:.3f}",
                            **common)
        if v < -self.theta_hz:
            return Decision(action=Action.SELL, status=ReadoutStatus.VALID,
                            reason=f"V {v:+.3f} Hz < -theta {self.theta_hz:.3f}",
                            **common)
        return Decision(action=Action.WAIT, status=ReadoutStatus.VALID,
                        reason=f"|V| {abs(v):.3f} Hz <= theta "
                               f"{self.theta_hz:.3f}",
                        **common)

    def decode(self, presentation) -> Decision:
        """Decode a :class:`flytrade.runner.Presentation`."""
        return self.decode_rates(
            presentation.mean(APPROACH), presentation.mean(AVOID),
            kc_fraction=presentation.kc_fraction,
            max_rate_hz=presentation.max_rate_hz)

    def score(self, evaluation) -> float | None:
        """Selection score for one candidate: its centred valence.

        ``None`` for a candidate the decoder cannot read, so that an unusable
        readout can never win a round by accident.
        """
        if evaluation.presentation is None:
            return None
        d = self.decode(evaluation.presentation)
        return d.valence_hz if d.status is ReadoutStatus.VALID else None

    def as_dict(self) -> dict:
        return {"version": self.version, "baseline_hz": self.baseline_hz,
                "theta_hz": self.theta_hz, "theta_sd": THETA_SD,
                "baseline_sd_hz": BASELINE_SD_HZ,
                "max_kc_fraction": self.max_kc_fraction,
                "saturated_hz": self.saturated_hz}
