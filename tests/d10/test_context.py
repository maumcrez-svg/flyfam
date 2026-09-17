"""``pons_context_v1``: causality, clipping, the three prices, absent vs neutral.

The tapes are scripted (``tests.d10.fixtures``, see its docstring): every
reserve, timestamp and trade size in this module is invented so a test can ask
for a token that is too young or one that stops trading. The feature code,
the curve arithmetic and the quote are real.
"""

from __future__ import annotations

import math

import pytest

from flytrade.market import ObservationStatus
from flytrade.pons.context import (MIN_AGE_S, MIN_TRADES, PAPER_SIZE_WEI,
                                   PONS_FEATURES, TokenTape)
from tests.d10 import fixtures as F


# ------------------------------------------------------------------ causality
def test_truncating_the_stream_at_the_cutoff_gives_the_same_vector():
    """Addendum 9's causality test, literally.

    A tape fed the whole history and a tape fed only the events at or before
    the cutoff must answer identically. If anything after the cutoff could
    reach a feature, these two would differ.
    """
    events = [F.buy_event("0x" + "b" * 40, at_seconds=s, quote_in=q,
                          state=None, log_index=i)
              for i, (s, q) in enumerate(())]  # placeholder, replaced below
    whole = F.tape()
    truncated = F.tape()
    cutoff = whole.launched_at + 180
    points = ((10, 5 * 10 ** 16), (40, 3 * 10 ** 16), (80, 7 * 10 ** 16),
              (130, 2 * 10 ** 16), (200, 9 * 10 ** 16), (260, 4 * 10 ** 16))
    for i, (second, quote) in enumerate(points):
        event = F.buy_event(whole.curve, at_seconds=second, quote_in=quote,
                            state=whole.state, log_index=i)
        whole.apply(event)
        if whole.points[-1].ts <= cutoff:
            truncated.apply(F.buy_event(truncated.curve, at_seconds=second,
                                        quote_in=quote, state=truncated.state,
                                        log_index=i))
    assert len(whole.points) > len(truncated.points)     # there *is* a future
    a = whole.context(cutoff)
    b = truncated.context(cutoff)
    assert a.raw == b.raw
    assert a.marginal_price == b.marginal_price
    assert a.last_trade_price == b.last_trade_price
    assert a.executable_tokens_out == b.executable_tokens_out
    assert events == []


def test_a_later_trade_cannot_move_an_earlier_cutoff():
    tape = F.traded_tape()
    cutoff = tape.launched_at + 100
    before = tape.context(cutoff).raw
    tape.apply(F.buy_event(tape.curve, at_seconds=300, quote_in=9 * 10 ** 17,
                           state=tape.state, log_index=99))
    assert tape.context(cutoff).raw == before


# ------------------------------------------------------------ clipped windows
def test_a_window_that_predates_the_launch_is_clipped_not_zeroed():
    """Reviewer decision 3. The whole point of the amendment.

    At 90 seconds old, the 5-minute window starts before the launch. The
    feature is measured *since the launch* and is non-zero, where the dispatch-1
    rule would have reported exactly 0.0 and lost the measurement.
    """
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 90)
    assert context.usable
    assert context.raw["ret_5m"] != 0.0
    assert context.raw["ret_2m"] != 0.0
    # and it equals the return since the launch, because the launch is later
    # than cutoff - 5 min
    price_now = context.marginal_price
    price_launch = tape.points[0].marginal_price
    assert context.raw["ret_5m"] == pytest.approx(
        math.log(price_now / price_launch))


def test_drawdown_is_measured_from_the_launch_when_the_window_predates_it():
    tape = F.tape()
    for i, (second, quote) in enumerate(((10, 8 * 10 ** 17), (20, 5 * 10 ** 17),
                                         (30, 10 ** 16))):
        tape.apply(F.buy_event(tape.curve, at_seconds=second, quote_in=quote,
                               state=tape.state, log_index=i))
    tape.apply(F.sell_event(tape.curve, at_seconds=50,
                            tokens_in=tape.state.token_reserve // 20,
                            state=tape.state, log_index=9))
    context = tape.context(tape.launched_at + 70)
    assert context.raw["drawdown_5m"] < 0.0         # it really did fall back


def test_a_window_with_no_trades_is_a_measurement_not_an_absence():
    """Addendum 9. Rate 0 and imbalance 0 are answers, not missing data."""
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 600)   # long after the last trade
    assert context.usable
    assert context.raw["trade_rate_2m"] == 0.0
    assert context.raw["flow_imb_2m"] == 0.0
    assert context.raw["rv_2m"] == 0.0
    assert context.raw["ret_2m"] == 0.0              # the price did not move


# ---------------------------------------------------------- absent, not neutral
def test_a_token_under_sixty_seconds_is_not_presented_and_says_why():
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + MIN_AGE_S - 1)
    assert not context.usable
    assert context.status is ObservationStatus.INSUFFICIENT_TAPE
    assert "age" in context.reason
    assert context.raw == {}


def test_a_token_with_too_few_trades_is_not_presented_and_says_why():
    tape = F.traded_tape(trades=((10, 10 ** 16), (20, 10 ** 16)))
    context = tape.context(tape.launched_at + 300)
    assert not context.usable
    assert context.status is ObservationStatus.INSUFFICIENT_TAPE
    assert f"< {MIN_TRADES}" in context.reason


def test_an_inconsistent_reconstruction_is_its_own_status():
    tape = F.traded_tape()
    corrupt = F.buy_event(tape.curve, at_seconds=200, quote_in=10 ** 16,
                          state=tape.state, log_index=7)
    corrupt["args"]["tokensOut"] = str(int(corrupt["args"]["tokensOut"]) + 1)
    tape.apply(corrupt)
    assert tape.inconsistent
    context = tape.context(tape.launched_at + 300)
    assert context.status is ObservationStatus.INCONSISTENT_STATE
    assert not context.usable


def test_a_completed_curve_has_its_own_status_not_inconsistency():
    tape = F.traded_tape()
    tape.apply(F.completed_event(tape.curve, at_seconds=200))
    context = tape.context(tape.launched_at + 300)
    assert context.status is ObservationStatus.ROUTE_COMPLETED
    assert not context.usable
    assert not tape.inconsistent


def test_an_unusable_observation_normalises_to_zeros_and_is_refused_by_the_encoder():
    """A zero vector is not a flat market: the caller must branch on status."""
    from flytrade.pons.encoder import SensoryEncoder, UnusableObservation
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 10)
    scales = {name: 1.0 for name in PONS_FEATURES}

    class Fake(SensoryEncoder):
        def __init__(self):                       # no annotations needed here
            self.features = PONS_FEATURES
            self.scales = scales

    with pytest.raises(UnusableObservation) as caught:
        SensoryEncoder.encode(Fake(), context, symbol="x")
    assert caught.value.status is ObservationStatus.INSUFFICIENT_TAPE


# ------------------------------------------------------------- three prices
def test_the_three_prices_are_three_separate_fields_and_differ():
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 180)
    assert context.marginal_price > 0
    assert context.last_trade_price > 0
    assert context.executable_tokens_out > 0
    # the last trade paid the all-in price including its own impact and fees,
    # so it is not the marginal price
    assert context.last_trade_price != context.marginal_price
    # and the executable amount-out is a token quantity, not a price
    assert context.executable_size_wei == PAPER_SIZE_WEI
    assert context.as_dict()["executable_tokens_out"] == str(
        context.executable_tokens_out)


def test_only_the_marginal_price_enters_a_feature():
    """Two tapes with the same marginal path but different trade prices."""
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 180)
    price_now = tape.point_at(tape.launched_at + 180).marginal_price
    earlier = tape.point_at(tape.launched_at + 60).marginal_price
    assert context.raw["ret_2m"] == pytest.approx(math.log(price_now / earlier))


# ----------------------------------------------------- determinism and shape
def test_the_same_tape_and_cutoff_give_the_identical_vector_every_time():
    tape = F.traded_tape()
    cutoff = tape.launched_at + 200
    first = tape.context(cutoff)
    for _ in range(5):
        again = tape.context(cutoff)
        assert again.raw == first.raw
        assert again.as_dict() == first.as_dict()


def test_the_normalised_vector_is_tanh_of_raw_over_scale():
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 180)
    scales = {"age": 600.0, "ret_30s": 0.0051, "ret_2m": 0.11, "ret_5m": 0.36,
              "flow_imb_2m": 1.0, "trade_rate_2m": 6.0, "rv_2m": 0.029,
              "drawdown_5m": 0.51}
    normalized = context.normalized(scales)
    for i, name in enumerate(PONS_FEATURES):
        assert normalized[i] == pytest.approx(
            math.tanh(context.raw[name] / scales[name]))
    assert all(-1.0 < x < 1.0 for x in normalized)


def test_a_non_positive_scale_is_refused_rather_than_divided_by():
    from flytrade.pons.context import ContextError
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 180)
    scales = {name: 1.0 for name in PONS_FEATURES}
    scales["rv_2m"] = 0.0
    with pytest.raises(ContextError):
        context.normalized(scales)


def test_coverage_is_the_window_not_the_last_trade():
    """A curve that stops trading is still covered, and still priceable."""
    tape = F.traded_tape()
    last_trade = tape.points[-1].ts
    assert tape.coverage_end() > last_trade
    assert tape.coverage_end() == tape.coverage_end_ts


def test_coverage_ends_at_the_completion_when_the_curve_completes():
    tape = F.traded_tape()
    tape.apply(F.completed_event(tape.curve, at_seconds=200))
    assert tape.coverage_end() == tape.completed_at
    assert tape.coverage_end() < tape.coverage_end_ts


def test_the_observation_carries_the_pons_feature_names_not_the_ibm_ones():
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 180, stable_id=3)
    scales = {name: 1.0 for name in PONS_FEATURES}
    obs = context.observation(scales, symbol=tape.token)
    assert tuple(obs.as_dict()["raw"]) == PONS_FEATURES
    assert len(obs.as_dict()["normalized"]) == len(PONS_FEATURES)
