"""
MarketToSensoryEncoder — market measurements into bounded ORN stimulation.

Canonical amendment §1 and Fable addendum 1. The encoder stimulates **only**
olfactory receptor neurons, on the ORN -> uPN path Phase 0.5 measured. It never
touches Kenyon cells, MBONs, PAM, PPL1 or any modulatory pathway: every effect
the market has on the mushroom body has to travel the sensory route, or it is
not an effect of the market on the fly.

## Channels

Candidate pool: the 46 glomeruli with both ORNs and uniglomerular PNs, minus
the four pheromone channels (``flytrade.sensory.candidate_glomeruli``,
pre-registered in ``experiments/conditioning/PROTOCOL.md`` §3).

From that pool the encoder takes channels by a rule fixed here, with no market
quantity in it:

1. keep candidates with at least :data:`MIN_UPNS` uniglomerular PNs — a
   channel needs a real projection to the calyx to be worth anything;
2. rank the survivors by ORN count, descending, ties alphabetical;
3. take the first ``2 x len(FEATURES)``;
4. pair them consecutively: pair *k* is ``(ranked[2k], ranked[2k+1])`` and
   carries feature *k*. Consecutive pairing keeps the two halves of a feature
   close in ORN count, so the sign of a feature is not confounded with the
   strength of its channel.

## Coding

Each feature ``u`` in (-1, 1) is given a per-glomerulus **weight** on its
antagonistic pair, half-wave rectified over a small always-on carrier ``C``::

    w(positive glomerulus) = C + (1 - C) * max(0, +u)
    w(negative glomerulus) = C + (1 - C) * max(0, -u)

Those weights are then scaled to a **constant total drive budget**::

    rate(g) = min(DRIVE_MAX_HZ, B * w(g) / sum_h w(h) * n_orns(h))

so every market state delivers the same total number of ORN spikes per second
to the antennal lobe, however many glomeruli it happens to engage. The
antennal lobe itself normalises divisively across glomeruli (Olsen, Bhandawat
& Wilson 2010, *Neuron* 66:287), so a constant-budget input is the regime the
downstream circuit is built for; here it is also what makes the encoder
measurable, because it decouples "which market state" from "how much drive".

This is the third coding rule tried, and the first two are kept selectable —
``coding="balanced"`` and ``coding="rectified"`` — purely so that
``experiments/phase_one/encoder_range.py`` can reproduce the measurements that
rejected them rather than leave them as an anecdote. Nothing downstream uses
anything but the default:

* ``balanced`` — ``(1 +/- u) / 2``, no rectification. Drives all ten glomeruli
  hard whatever the market does; measured pairwise Kenyon-cell Jaccard
  0.57-0.78 against the 0.40 threshold. Rejected.
* ``rectified`` — rectified, fixed per-ORN rate, no budget. Discrimination and
  silence trade directly against each other: every setting that reached
  Jaccard < 0.40 also produced silent MBON readouts. Rejected.

The carrier ``C`` exists because the simulation has no spontaneous activity, so
a flat tape encoded at exactly zero drive would be indistinguishable from
"nothing was measured" (`docs/ARCHITECTURE.md`, constraint 1). It is set to the
smallest declared value that leaves no silent readout; any larger carrier only
costs discrimination.

Per-ORN rates stay inside ``[0, DRIVE_MAX_HZ]`` with ``DRIVE_MAX_HZ <= 150``,
which is addendum 1's window.

All ORNs of a glomerulus receive the same rate. Channel weight is not
equalised across features: the budget is shared in proportion to ``w(g) *
n_orns(g)``, so a glomerulus with 98 ORNs claims more of it than one with 48.
The weighting is reported in ``docs/ENCODER.md`` rather than hidden.

Ticker identity is **not** encoded. Two instruments with identical normalised
features produce an identical stimulus, by design: amendment §1 says ticker
identity is metadata, not a hand-encoded financial preference.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import market as MK
from . import populations as P
from . import sensory as S

VERSION = "flytrade-encoder-1"

#: a channel needs at least this many uniglomerular PNs to be usable
MIN_UPNS = 4

#: total ORN drive per presentation, in Hz summed over every driven ORN. This
#: is the encoder's declared input operating point; see ``docs/ENCODER.md`` for
#: the measurement that chose it.
DRIVE_BUDGET_HZ = 12000.0

#: hard per-ORN ceiling, Hz. Addendum 1's window is [0, 150].
DRIVE_MAX_HZ = 150.0

#: always-on carrier as a fraction of a channel's full weight, so that a flat
#: market is a weak stimulus rather than an absence of one.
CARRIER = 0.10

#: the coding rule in use. The other two are kept only for reproducing the
#: measurements that rejected them.
CODING = "normalized"
CODINGS = ("normalized", "rectified", "balanced")

#: presentation window: 100 steps x 0.2 ms = 20 ms of brain time, unchanged
#: from PROTOCOL.md §2.
STEPS = S.STEPS

#: uniform synaptic-efficacy multiplier. D2: frozen at 0.10, never tuned.
GLOBAL_GAIN = S.GLOBAL_GAIN


@dataclass(frozen=True)
class Channel:
    """One feature's antagonistic glomerulus pair."""

    feature: str
    positive: str
    negative: str
    pos_orns: np.ndarray = field(repr=False)
    neg_orns: np.ndarray = field(repr=False)


@dataclass(frozen=True)
class Stimulus:
    """What the encoder produced for one observation.

    ``drive`` is the dict ``flysim.FlyBrain.run`` consumes. ``rates`` is the
    same information keyed by glomerulus, for the record and the documentation.
    """

    symbol: str
    stable_id: int
    bar_index: int
    cutoff_ts: int
    encoder_version: str
    normalized: np.ndarray
    rates: dict[str, float]
    drive: dict = field(repr=False)
    n_orns: int
    total_drive_hz: float

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "stable_id": self.stable_id,
            "bar_index": self.bar_index, "cutoff_ts": self.cutoff_ts,
            "encoder_version": self.encoder_version,
            "normalized": [float(x) for x in self.normalized],
            "rates_hz": {k: round(float(v), 4) for k, v in self.rates.items()},
            "n_orns": self.n_orns,
            "total_drive_hz": round(float(self.total_drive_hz), 3),
        }


def channel_glomeruli(ann: P.Annotations, *, n_features: int = len(MK.FEATURES),
                      min_upns: int = MIN_UPNS) -> list[tuple[str, str]]:
    """The glomerulus pairs, by the rule in this module's docstring."""
    og, ug = P.orn_glomeruli(ann), P.upn_glomeruli(ann)
    pool = [g for g in S.candidate_glomeruli(ann) if len(ug[g]) >= min_upns]
    ranked = sorted(pool, key=lambda g: (-len(og[g]), g))
    need = 2 * n_features
    if len(ranked) < need:
        raise ValueError(f"only {len(ranked)} candidate glomeruli with "
                         f">= {min_upns} uPNs; {need} needed")
    top = ranked[:need]
    return [(top[2 * k], top[2 * k + 1]) for k in range(n_features)]


class MarketToSensoryEncoder:
    """Deterministic, versioned market -> ORN drive.

    The encoder holds no state that changes between calls: the same
    observation always produces the same stimulus. Randomness enters only
    downstream, in the Poisson drive of ``FlyBrain.run``, whose seed is
    recorded per candidate.
    """

    version = VERSION

    def __init__(self, ann: P.Annotations, *,
                 drive_budget_hz: float = DRIVE_BUDGET_HZ,
                 drive_max_hz: float = DRIVE_MAX_HZ,
                 carrier: float = CARRIER,
                 coding: str = CODING,
                 min_upns: int = MIN_UPNS,
                 features: tuple[str, ...] = MK.FEATURES):
        if not 0.0 < drive_max_hz <= 150.0:
            raise ValueError("drive_max_hz must lie in (0, 150] Hz "
                             "(Fable addendum 1)")
        if not 0.0 <= carrier < 1.0:
            raise ValueError("carrier must lie in [0, 1)")
        if coding not in CODINGS:
            raise ValueError(f"coding must be one of {CODINGS}")
        if drive_budget_hz <= 0.0:
            raise ValueError("drive_budget_hz must be positive")
        self.features = tuple(features)
        self.drive_budget_hz = float(drive_budget_hz)
        self.drive_max_hz = float(drive_max_hz)
        self.carrier = float(carrier)
        self.coding = coding
        og = P.orn_glomeruli(ann)
        pairs = channel_glomeruli(ann, n_features=len(self.features),
                                  min_upns=min_upns)
        self.channels = tuple(
            Channel(feature=f, positive=p, negative=n,
                    pos_orns=og[p], neg_orns=og[n])
            for f, (p, n) in zip(self.features, pairs))
        self.glomeruli = tuple(g for c in self.channels
                               for g in (c.positive, c.negative))
        self.orn_count = {g: int(len(og[g])) for g in self.glomeruli}
        self.n_orns = int(sum(self.orn_count.values()))

    # -- encoding ---------------------------------------------------------

    def weights(self, normalized) -> dict[str, float]:
        """Per-glomerulus weight in [0, 1] for a normalised feature vector."""
        u = np.asarray(normalized, dtype=np.float64)
        if u.shape != (len(self.channels),):
            raise ValueError(f"expected {len(self.channels)} features, "
                             f"got {u.shape}")
        if not np.all(np.isfinite(u)):
            raise ValueError("normalised features must be finite")
        u = np.clip(u, -1.0, 1.0)
        c0, c1 = self.carrier, 1.0 - self.carrier
        out: dict[str, float] = {}
        for c, x in zip(self.channels, u):
            x = float(x)
            if self.coding == "balanced":
                out[c.positive] = (1.0 + x) / 2.0
                out[c.negative] = (1.0 - x) / 2.0
            else:
                out[c.positive] = c0 + c1 * max(0.0, x)
                out[c.negative] = c0 + c1 * max(0.0, -x)
        return out

    def rates(self, normalized) -> dict[str, float]:
        """Per-ORN drive in Hz per glomerulus, for a normalised feature vector."""
        w = self.weights(normalized)
        if self.coding != "normalized":
            return {g: self.drive_max_hz * x for g, x in w.items()}
        load = sum(x * self.orn_count[g] for g, x in w.items())
        if load <= 0.0:
            return {g: 0.0 for g in w}
        k = self.drive_budget_hz / load
        return {g: min(self.drive_max_hz, k * x) for g, x in w.items()}

    def encode(self, obs: MK.MarketObservation) -> Stimulus:
        """Turn a usable observation into ORN drive.

        Raises on an unusable observation. The caller must branch on
        ``obs.status`` first: an unusable observation is not a flat market and
        must never be encoded as one.
        """
        if not obs.status.usable:
            raise ValueError(
                f"{obs.symbol}: observation is {obs.status.value} "
                f"({obs.detail}); it cannot be encoded")
        return self.encode_features(
            obs.normalized, symbol=obs.symbol, stable_id=obs.stable_id,
            bar_index=obs.bar_index, cutoff_ts=obs.cutoff_ts)

    def encode_features(self, normalized, *, symbol: str = "",
                        stable_id: int = -1, bar_index: int = -1,
                        cutoff_ts: int = 0) -> Stimulus:
        """Encode a normalised feature vector directly.

        Used by the operating-range measurement, which needs to place nominal
        patterns at chosen points of the input range rather than find bars
        that happen to sit there.
        """
        rates = self.rates(normalized)
        drive, total = {}, 0.0
        for c in self.channels:
            for glom, orns in ((c.positive, c.pos_orns),
                               (c.negative, c.neg_orns)):
                hz = rates[glom]
                drive[tuple(int(i) for i in orns)] = float(hz)
                total += hz * len(orns)
        return Stimulus(
            symbol=symbol, stable_id=stable_id, bar_index=bar_index,
            cutoff_ts=cutoff_ts, encoder_version=self.version,
            normalized=np.asarray(normalized, dtype=np.float64).copy(),
            rates=rates, drive=drive, n_orns=self.n_orns,
            total_drive_hz=total)

    # -- documentation ----------------------------------------------------

    def channel_table(self, ann: P.Annotations) -> list[dict]:
        ug = P.upn_glomeruli(ann)
        rows = []
        for c in self.channels:
            rows.append({
                "feature": c.feature,
                "positive": c.positive, "pos_orns": int(len(c.pos_orns)),
                "pos_upns": int(len(ug[c.positive])),
                "negative": c.negative, "neg_orns": int(len(c.neg_orns)),
                "neg_upns": int(len(ug[c.negative])),
            })
        return rows

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "features": list(self.features),
            "coding": self.coding,
            "drive_budget_hz": self.drive_budget_hz,
            "drive_max_hz": self.drive_max_hz,
            "carrier": self.carrier,
            "steps": STEPS,
            "global_gain": GLOBAL_GAIN,
            "glomeruli": list(self.glomeruli),
            "n_orns": self.n_orns,
        }
