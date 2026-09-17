"""``admission_v2`` — which launches may be measured, with recent activity.

docs/SPEC.md D11 amendment §3 and Fable addendum 3. ``admission_v1``
(:mod:`flytrade.pons.admission`) is left **byte-identical** beside this module.

v1 admitted a curve on "at least three trades ever". With 59 % of launches
silent five minutes after birth and 77 % silent at fifteen, that made the
candidate pool mostly corpses, and fifteen of D10's seventeen entries were
taken on a token that had not traded for between eight and fifty-eight minutes.
v2 keeps every objective fact v1 required and replaces that one clause with a
**recency** rule:

    at least ``minimum_valid_trades_in_window`` valid trades inside
    ``(cutoff − recent_window_seconds, cutoff]``, and the last of them at most
    ``maximum_seconds_since_last_trade`` before the cutoff.

The three constants are **fixed engineering defaults, declared in
``experiments/d11/config.json`` before any D11 number was computed**. They are
not a discovery about which tokens profit, they are not searched, and they are
not revisited after a run is observed. A *valid trade* is
:func:`flytrade.pons.context_v2.is_valid_trade` — the same definition the
sensory features use, imported from there rather than restated, so the rule and
the input can never disagree.

**This is not a classifier.** Admission never ranks by future returns, eventual
survival, ticker, the direction of a recent return, promoter identity or a
desired trading outcome. It is a recent-activity filter and must never be
reported as an organic-flow, anti-manipulation or profitability test.

**Reversible by construction.** Every tick recomputes every candidate from the
tape as it stands, so an inactive candidate is readmitted the moment new
qualifying activity appears. Nothing survives a tick except the rotation
counter.

**Four different silences, four different names.** ``INACTIVE`` is a complete
tape with no recent trades. ``INSUFFICIENT_HISTORY`` is a tape too short to
answer. ``COLLECTOR_LAG`` is *our* data being late, and when it covers the
whole tracked set the round is ``DATA_LAG`` — a collector outage can never be
reported as every token becoming inactive. ``NO_RESPONSE`` belongs to the
readout and never appears here.

**Admission controls new entries only.** A held position is observed, marked
and settled at its own horizon whatever admission says about its token.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import market as MK
from .admission import ROTATED, Candidate
from .context import MIN_AGE_S, PAPER_SIZE_WEI, PonsContext, TokenTape
from .context_v2 import recent_activity
from .curve import QuoteError, quote_curve_buy
from .manifest import NATIVE_QUOTE

VERSION = "admission_v2"

#: Addendum 9 of D10 / amendment §9: at most six neural candidates per round.
MAX_CANDIDATES = 6

#: The three fixed engineering defaults, registered before any D11 number.
RECENT_WINDOW_S = 120
MIN_VALID_TRADES_IN_WINDOW = 2
MAX_SECONDS_SINCE_LAST_TRADE = 60

#: How late our own data may be before a candidate is ``COLLECTOR_LAG``:
#: two ticks of the declared cadence. Replay never sets ``data_as_of`` and so
#: can never raise it.
COLLECTOR_LAG_TICKS = 2
CADENCE_S = 30

# -- the reason vocabulary. Distinct from each other, from the observation
# -- statuses and from the readout's statuses.
INACTIVE = "INACTIVE"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
COLLECTOR_LAG = "COLLECTOR_LAG"
QUOTE_UNSUPPORTED = "QUOTE_UNSUPPORTED"
ROUTE_COMPLETED = "ROUTE_COMPLETED"
STATE_INVALID = "STATE_INVALID"
COVERAGE = "COVERAGE"
CURVE_EXHAUSTED = "CURVE_EXHAUSTED"
#: Carried unchanged from v1. A DECLARED addition to the eight codes addendum 3
#: names: dropping it would either admit a v1-factory curve or mislabel it as
#: ``QUOTE_UNSUPPORTED``, and those are different facts.
DEPLOYMENT_UNSUPPORTED = "DEPLOYMENT_UNSUPPORTED"

REASON_CODES = (INACTIVE, INSUFFICIENT_HISTORY, COLLECTOR_LAG,
                QUOTE_UNSUPPORTED, ROUTE_COMPLETED, STATE_INVALID, COVERAGE,
                CURVE_EXHAUSTED, DEPLOYMENT_UNSUPPORTED, ROTATED)

#: Round statuses. Neither is a readout status and neither is a WAIT.
NO_ELIGIBLE_CANDIDATES = "NO_ELIGIBLE_CANDIDATES"
DATA_LAG = "DATA_LAG"


@dataclass
class AdmissionPolicyV2:
    """The versioned rule, its parameters recorded rather than implied."""

    version: str = VERSION
    size_wei: int = PAPER_SIZE_WEI
    latency_s: int = 2
    horizon_s: int = 900
    max_candidates: int = MAX_CANDIDATES
    supported_deployment: str = "pons-v2"
    quote_asset: str = NATIVE_QUOTE
    require_coverage: bool = True
    recent_window_s: int = RECENT_WINDOW_S
    min_valid_trades_in_window: int = MIN_VALID_TRADES_IN_WINDOW
    max_seconds_since_last_trade: int = MAX_SECONDS_SINCE_LAST_TRADE
    cadence_s: int = CADENCE_S
    collector_lag_ticks: int = COLLECTOR_LAG_TICKS
    #: The chain second our own data reaches, set by the live driver once per
    #: tick. ``None`` — replay, and every fixture — can never lag.
    data_as_of: int | None = None
    #: round index at which each stable id was last presented
    last_presented: dict = field(default_factory=dict)

    # ------------------------------------------------------------ lagging
    @property
    def collector_lag_seconds(self) -> int:
        return int(self.collector_lag_ticks) * int(self.cadence_s)

    def lagging(self, cutoff: int) -> bool:
        """Is our own view of the chain more than two ticks behind the cutoff?"""
        if self.data_as_of is None:
            return False
        return int(cutoff) - int(self.data_as_of) > self.collector_lag_seconds

    # -------------------------------------------------------------- admit
    def consider(self, tape: TokenTape, context: PonsContext, *,
                 stable_id: int, cutoff: int,
                 launch_log_index: int = 0) -> Candidate:
        """One launch, one cutoff, every reason it did or did not qualify."""
        reasons: list[str] = []
        lagging = self.lagging(cutoff)
        if tape.deployment != self.supported_deployment:
            reasons.append(DEPLOYMENT_UNSUPPORTED)
        if tape.quote_asset != self.quote_asset:
            reasons.append(QUOTE_UNSUPPORTED)
        if lagging:
            reasons.append(COLLECTOR_LAG)

        status = context.status
        if status is MK.ObservationStatus.ROUTE_COMPLETED or tape.completed_by(cutoff):
            if ROUTE_COMPLETED not in reasons:
                reasons.append(ROUTE_COMPLETED)
        elif status is MK.ObservationStatus.INCONSISTENT_STATE:
            reasons.append(STATE_INVALID)
        elif status is MK.ObservationStatus.INSUFFICIENT_TAPE:
            reasons.append(INSUFFICIENT_HISTORY)
        elif not context.usable:
            # Any other unusable status keeps its own name rather than being
            # folded into one of the four silences.
            reasons.append(str(status.value))

        state = tape.state_at(cutoff)
        if state is None or state.sellable_tokens <= 0 or state.real_quote_reserve <= 0:
            if STATE_INVALID not in reasons:
                reasons.append(STATE_INVALID)
        elif not reasons:
            try:
                quote = quote_curve_buy(state, int(self.size_wei))
            except QuoteError:
                reasons.append(STATE_INVALID)
            else:
                if quote.refund > 0 or quote.tokens_out >= state.sellable_tokens:
                    reasons.append(CURVE_EXHAUSTED)
        if self.require_coverage:
            need = int(cutoff) + int(self.latency_s) + int(self.horizon_s)
            if need > tape.coverage_end():
                reasons.append(COVERAGE)

        # The recency rule, last, and only on a tape that is both complete and
        # long enough to answer: an inactive candidate and a candidate whose
        # data we simply do not have yet are different facts and never share a
        # counter.
        if not lagging and INSUFFICIENT_HISTORY not in reasons:
            act = recent_activity(tape, cutoff, window_s=self.recent_window_s)
            since = act["since_last_trade_s"]
            if (act["trades_in_window"] < self.min_valid_trades_in_window
                    or since is None
                    or since > self.max_seconds_since_last_trade):
                reasons.append(INACTIVE)

        return Candidate(
            token=tape.token, curve=tape.curve, stable_id=int(stable_id),
            context=context, admitted=not reasons, reasons=tuple(reasons),
            last_presented_round=int(self.last_presented.get(int(stable_id), -1)),
            launch_block=int(tape.launch_block),
            launch_log_index=int(launch_log_index))

    # ------------------------------------------------------------- rotate
    def rotate(self, candidates, round_index: int) -> tuple[list, list]:
        """``(presented, omitted)`` — round-robin, blind to every price.

        Unchanged from v1: the key is (rounds since last presentation,
        descending; launch block; launch log index; address). Fewer than
        ``max_candidates`` are presented when fewer qualify, and nothing is
        relaxed to fill the slots.
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

    # -------------------------------------------------------- empty round
    def empty_round_status(self, considered) -> str:
        """The name of a round that presents nothing.

        ``DATA_LAG`` only when *every* considered token was excluded by
        ``COLLECTOR_LAG`` and at least one token was considered. Anything else
        — including an empty tracked set — is ``NO_ELIGIBLE_CANDIDATES``.
        """
        rows = list(considered)
        if rows and all(COLLECTOR_LAG in (c.reasons or ()) for c in rows):
            return DATA_LAG
        return NO_ELIGIBLE_CANDIDATES

    @staticmethod
    def reason_histogram(considered) -> dict:
        """Per-reason counts for the round's record. Every token, every reason."""
        out: dict[str, int] = {}
        for candidate in considered:
            for reason in (candidate.reasons or ("ADMITTED",)):
                out[reason] = out.get(reason, 0) + 1
        return out

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
            "recent_window_seconds": self.recent_window_s,
            "minimum_valid_trades_in_window": self.min_valid_trades_in_window,
            "maximum_seconds_since_last_trade": self.max_seconds_since_last_trade,
            "collector_lag_seconds": self.collector_lag_seconds,
            "minimum_age_seconds": MIN_AGE_S,
            "rules": [
                "deployment is the supported pons-v2 curve route",
                "quote asset is native ETH",
                "age >= 60 s and the reconstructed tape answers at the cutoff",
                "curve not completed at the cutoff",
                "sellableTokens > 0 and realQuoteReserve > 0",
                "the paper buy of size_wei would not exhaust the curve",
                "cutoff + latency + horizon lies inside the token's coverage",
                ("at least minimum_valid_trades_in_window valid trades inside "
                 "(cutoff - recent_window_seconds, cutoff]"),
                ("the last valid trade at most "
                 "maximum_seconds_since_last_trade before the cutoff"),
            ],
            "valid_trade": ("CurveBuy or CurveSell with a nonzero quote leg and "
                            "a nonzero token leg, deduplicated by log id; "
                            "buys and sells count the same; creation, liquidity "
                            "configuration, completion and duplicated logs are "
                            "not trades"),
            "removed_from_v1": "the '>= 3 trades ever' clause of pons_context_v1",
            "rotation": ("round-robin: rounds since last presentation "
                         "descending, then launch block, then launch log index, "
                         "then curve address; blind to price, volume, flow and "
                         "outcome"),
            "reversible": ("recomputed fresh at every tick; an inactive "
                           "candidate returns on new qualifying activity"),
            "controls_new_entries_only": True,
            "reason_codes": list(REASON_CODES),
            "round_statuses": [NO_ELIGIBLE_CANDIDATES, DATA_LAG],
        }


__all__ = ["VERSION", "MAX_CANDIDATES", "RECENT_WINDOW_S",
           "MIN_VALID_TRADES_IN_WINDOW", "MAX_SECONDS_SINCE_LAST_TRADE",
           "COLLECTOR_LAG_TICKS", "CADENCE_S", "AdmissionPolicyV2",
           "Candidate", "REASON_CODES", "INACTIVE", "INSUFFICIENT_HISTORY",
           "COLLECTOR_LAG", "QUOTE_UNSUPPORTED", "ROUTE_COMPLETED",
           "STATE_INVALID", "COVERAGE", "CURVE_EXHAUSTED",
           "DEPLOYMENT_UNSUPPORTED", "ROTATED", "NO_ELIGIBLE_CANDIDATES",
           "DATA_LAG"]
