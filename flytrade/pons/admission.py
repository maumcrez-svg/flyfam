"""``admission_v1`` — which launches may be measured, and whose turn it is.

docs/SPEC.md D10 addendum 10 and amendment §7. Two rules live here and both
are deliberately blind to anything that could look like a trading opinion.

**Admission** is a conjunction of objective facts at the cutoff:

* the deployment is ``pons-v2`` (the supported curve route);
* the quote asset is native ETH;
* the observation is usable (``pons_context_v1``: age ≥ 60 s, ≥ 3 trades, a
  consistent reconstructed state);
* the curve has not completed at the cutoff;
* the reconstructed state is valid — ``sellableTokens > 0`` and
  ``realQuoteReserve > 0``;
* the paper buy of the declared size would **not** exhaust the curve;
* in replay, ``cutoff + latency + horizon`` lies inside the token's coverage.

Every launch gets a record whether it is admitted or not, with its reason
codes, so the dataset is the launches that happened and not the launches that
survived (amendment §7: "do not build the dataset from today's survivors").

**Rotation** is round-robin and nothing else. When more than the maximum
qualify, they are ordered by rounds since last presentation (descending), then
launch block, then log index, then address — no price, no volume, no flow, no
outcome, no ticker. The omitted are recorded ``ROTATED``.

Admission statuses, neural statuses and execution rejections are three
different vocabularies and this module only speaks the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .context import PAPER_SIZE_WEI, PonsContext, TokenTape
from .curve import QuoteError, quote_curve_buy
from .manifest import NATIVE_QUOTE

VERSION = "admission_v1"

#: Addendum 9 / amendment §9: at most six neural candidates per round.
MAX_CANDIDATES = 6

#: The reason codes. A launch may carry several; they are all recorded.
NOT_SUPPORTED = "DEPLOYMENT_UNSUPPORTED"
QUOTE_UNSUPPORTED = "QUOTE_UNSUPPORTED"
UNUSABLE = "OBSERVATION_UNUSABLE"
COMPLETED = "CURVE_COMPLETED"
STATE_INVALID = "STATE_INVALID"
WOULD_EXHAUST = "WOULD_EXHAUST_CURVE"
COVERAGE = "COVERAGE"
ROTATED = "ROTATED"


@dataclass
class Candidate:
    """One token considered at one round, admitted or not."""

    token: str
    curve: str
    stable_id: int
    context: PonsContext
    admitted: bool
    reasons: tuple[str, ...] = ()
    last_presented_round: int = -1
    launch_block: int = 0
    launch_log_index: int = 0

    def as_dict(self) -> dict:
        return {"token": self.token, "curve": self.curve,
                "stable_id": self.stable_id, "admitted": self.admitted,
                "reasons": list(self.reasons),
                "status": self.context.status.value,
                "age_s": self.context.age_s,
                "trades": self.context.trades,
                "last_presented_round": self.last_presented_round}


@dataclass
class AdmissionPolicy:
    """The versioned rule, its parameters recorded rather than implied."""

    version: str = VERSION
    size_wei: int = PAPER_SIZE_WEI
    latency_s: int = 2
    horizon_s: int = 900
    max_candidates: int = MAX_CANDIDATES
    supported_deployment: str = "pons-v2"
    quote_asset: str = NATIVE_QUOTE
    require_coverage: bool = True
    #: round index at which each stable id was last presented
    last_presented: dict = field(default_factory=dict)

    # -------------------------------------------------------------- admit
    def consider(self, tape: TokenTape, context: PonsContext, *,
                 stable_id: int, cutoff: int,
                 launch_log_index: int = 0) -> Candidate:
        """One launch, one cutoff, every reason it did or did not qualify."""
        reasons: list[str] = []
        if tape.deployment != self.supported_deployment:
            reasons.append(NOT_SUPPORTED)
        if tape.quote_asset != self.quote_asset:
            reasons.append(QUOTE_UNSUPPORTED)
        if not context.usable:
            reasons.append(UNUSABLE)
        if tape.completed_by(cutoff):
            reasons.append(COMPLETED)
        state = tape.state_at(cutoff)
        if state is None or state.sellable_tokens <= 0 or state.real_quote_reserve <= 0:
            reasons.append(STATE_INVALID)
        elif not reasons:
            try:
                quote = quote_curve_buy(state, int(self.size_wei))
            except QuoteError:
                reasons.append(STATE_INVALID)
            else:
                if quote.refund > 0 or quote.tokens_out >= state.sellable_tokens:
                    reasons.append(WOULD_EXHAUST)
        if self.require_coverage:
            need = int(cutoff) + int(self.latency_s) + int(self.horizon_s)
            if need > tape.coverage_end():
                reasons.append(COVERAGE)
        return Candidate(
            token=tape.token, curve=tape.curve, stable_id=int(stable_id),
            context=context, admitted=not reasons, reasons=tuple(reasons),
            last_presented_round=int(self.last_presented.get(int(stable_id), -1)),
            launch_block=int(tape.launch_block),
            launch_log_index=int(launch_log_index))

    # ------------------------------------------------------------- rotate
    def rotate(self, candidates, round_index: int) -> tuple[list, list]:
        """``(presented, omitted)`` — round-robin, blind to every price.

        The key is (rounds since last presentation, descending; launch block;
        launch log index; address). A token never presented sorts first, and
        ties go to the earliest launch. Nothing in the key can be influenced by
        what a token is worth or by how it has been doing.
        """
        admitted = [c for c in candidates if c.admitted]
        ordered = sorted(admitted, key=lambda c: (
            -(int(round_index) - c.last_presented_round),
            c.launch_block, c.launch_log_index, c.curve))
        presented = ordered[:self.max_candidates]
        omitted = ordered[self.max_candidates:]
        for candidate in omitted:
            candidate.reasons = tuple(candidate.reasons) + (ROTATED,)
        return presented, omitted

    def mark_presented(self, candidates, round_index: int) -> None:
        for candidate in candidates:
            self.last_presented[int(candidate.stable_id)] = int(round_index)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "size_wei": str(self.size_wei),
            "latency_s": self.latency_s,
            "horizon_s": self.horizon_s,
            "max_candidates": self.max_candidates,
            "supported_deployment": self.supported_deployment,
            "quote_asset": self.quote_asset,
            "require_coverage": self.require_coverage,
            "rules": [
                "deployment is the supported pons-v2 curve route",
                "quote asset is native ETH",
                "observation usable under pons_context_v1",
                "curve not completed at the cutoff",
                "sellableTokens > 0 and realQuoteReserve > 0",
                "the paper buy of size_wei would not exhaust the curve",
                "cutoff + latency + horizon lies inside the token's coverage",
            ],
            "rotation": ("round-robin: rounds since last presentation "
                         "descending, then launch block, then launch log index, "
                         "then curve address; blind to price, volume, flow and "
                         "outcome"),
            "reason_codes": [NOT_SUPPORTED, QUOTE_UNSUPPORTED, UNUSABLE,
                             COMPLETED, STATE_INVALID, WOULD_EXHAUST, COVERAGE,
                             ROTATED],
        }


__all__ = ["VERSION", "MAX_CANDIDATES", "AdmissionPolicy", "Candidate",
           "NOT_SUPPORTED", "QUOTE_UNSUPPORTED", "UNUSABLE", "COMPLETED",
           "STATE_INVALID", "WOULD_EXHAUST", "COVERAGE", "ROTATED"]
