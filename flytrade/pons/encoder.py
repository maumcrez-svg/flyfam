"""``pons_encoder_v1`` — the versioned sensory interface, olfactory only.

docs/SPEC.md D10 amendment §8 and addendum 9, with correction (c): **the
visual adapter and every non-olfactory modality are out of this wave**. What
this module delivers is the *interface* the amendment asks for — a
:class:`SensoryEncoder` with explicit modality outputs — wrapped around the
olfactory path this repository has already measured, so a later wave can add a
verified modality without touching market collection or execution.

:meth:`SensoryEncoder.encode` returns ``{"olfactory": Stimulus}`` and nothing
else. ``visual``, ``taste`` and ``mechanosensory`` are named in
:data:`EXTENSION_POINTS` as unimplemented and nowhere else: there is no stub
that returns zeros, because a modality that returns zeros is indistinguishable
from one that was never measured, and the amendment forbids exactly that
confusion.

The olfactory channel is :class:`flytrade.encoder.MarketToSensoryEncoder`
unchanged, built with this wave's eight features instead of the five
minute-bar ones. Two glomerular channels per feature means sixteen channels;
if ``channel_glomeruli`` cannot supply that many at the declared ``MIN_UPNS``,
features are dropped **from the end of** :data:`PONS_FEATURES` and the
dropped names are recorded in :attr:`SensoryEncoder.dropped` and in the run's
config. Nothing is silently rescaled or folded together.

Normalisation is ``tanh(raw / scale)`` with the fixed scales the config
declares (addendum 9): the IBM 60-bar causal z-score needs 81 bars of history
and cannot apply to a token ninety seconds old.
"""

from __future__ import annotations

from .. import encoder as E
from .. import market as MK
from .context import PONS_FEATURES, PonsContext

VERSION = "pons_encoder_v1"

#: Named, unimplemented, and not routed anywhere. Correction (c).
EXTENSION_POINTS = ("visual", "taste", "mechanosensory")

#: The one modality this wave implements.
OLFACTORY = "olfactory"


class UnusableObservation(ValueError):
    """The observation was not presentable, and the reason travels with it."""

    def __init__(self, status: MK.ObservationStatus, reason: str):
        super().__init__(f"{status.value}: {reason}")
        self.status = status
        self.reason = reason


class SensoryEncoder:
    """Versioned market context → modality-keyed stimuli. Olfactory only.

    ``scales`` maps every retained feature to its declared positive scale.
    ``ann`` is the annotation set the brain was built from; the channel map is
    derived from it by the rule in :mod:`flytrade.encoder`, which contains no
    market quantity.
    """

    version = VERSION
    modalities = (OLFACTORY,)
    extension_points = EXTENSION_POINTS

    def __init__(self, ann, scales: dict, *,
                 features: tuple[str, ...] = PONS_FEATURES,
                 min_upns: int = E.MIN_UPNS, **encoder_kw):
        requested = tuple(features)
        retained, dropped = self._fit(ann, requested, min_upns)
        missing = [f for f in retained if f not in scales]
        if missing:
            raise ValueError(f"no declared scale for {missing}")
        self.features = retained
        self.dropped = tuple(dropped)
        self.scales = {f: float(scales[f]) for f in retained}
        self.olfactory = E.MarketToSensoryEncoder(
            ann, features=retained, min_upns=min_upns, **encoder_kw)
        self.ann = ann

    @staticmethod
    def _fit(ann, features: tuple[str, ...], min_upns: int):
        """As many features as there are channel pairs, dropping from the end."""
        retained = list(features)
        dropped: list[str] = []
        while retained:
            try:
                E.channel_glomeruli(ann, n_features=len(retained),
                                    min_upns=min_upns)
                return tuple(retained), dropped
            except ValueError:
                dropped.insert(0, retained.pop())
        raise ValueError("no feature fits the available glomerular channels")

    # ----------------------------------------------------------- encoding
    def observation(self, context: PonsContext, *, symbol: str
                    ) -> MK.MarketObservation:
        return context.observation(self.scales, symbol=symbol,
                                   features=self.features)

    def encode(self, context: PonsContext, *, symbol: str) -> dict:
        """``{"olfactory": Stimulus}`` for a usable context.

        Raises :class:`UnusableObservation` otherwise. An unusable observation
        is **not** a flat market and must never be encoded as one: the caller
        branches on ``context.status`` first and records the reason.
        """
        if not context.usable:
            raise UnusableObservation(context.status, context.reason)
        obs = self.observation(context, symbol=symbol)
        return {OLFACTORY: self.olfactory.encode(obs)}

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "modalities": list(self.modalities),
            "extension_points": list(self.extension_points),
            "extension_points_implemented": False,
            "features": list(self.features),
            "features_requested": list(PONS_FEATURES),
            "features_dropped": list(self.dropped),
            "normalisation": "tanh(raw / scale), fixed declared scales",
            "scales": dict(self.scales),
            "channels": self.olfactory.channel_table(self.ann),
            "olfactory": self.olfactory.as_dict(),
        }


__all__ = ["VERSION", "OLFACTORY", "EXTENSION_POINTS", "SensoryEncoder",
           "UnusableObservation"]
