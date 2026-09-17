"""
Canonical amendment §6 — simulated execution, accounting and outcomes.

These tests need no connectome: the execution policy is arithmetic over bars
and holds no neural state at all. That separation is the point — nothing in
`flytrade/execution.py` can see a firing rate, and nothing in the decoder can
see a price.
"""
from __future__ import annotations

import math

import pytest

from flytrade import execution as X
from flytrade import market as MK


def _flat_series(symbol="TEST", n=60, price=100.0, step=0.0):
    bars = tuple(MK.Bar(ts=MK.SYNTHETIC_EPOCH + i * MK.BAR_SECONDS,
                        open=price + i * step, high=price + i * step + 1,
                        low=price + i * step - 1, close=price + i * step,
                        volume=1000.0) for i in range(n))
    return MK.Series(symbol, bars, MK.BAR_SECONDS)


def _policy(series=None, **kw):
    series = series or {"TEST": _flat_series()}
    return X.ExecutionPolicy(MK.ExecutionFeed(series), **kw)


# ----------------------------------------------------------- timing

def test_execution_never_happens_on_the_decision_bar():
    p = _policy()
    assert p.execution_bar(10) == 10 + p.delay_bars
    assert p.delay_bars >= 1
    pos = p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=10)
    assert isinstance(pos, X.Position)
    assert pos.entry.bar_index == 11
    assert pos.entry.ts == MK.SYNTHETIC_EPOCH + 11 * MK.BAR_SECONDS
    with pytest.raises(ValueError, match="delay_bars must be at least 1"):
        _policy(delay_bars=0)


def test_fill_is_the_next_bars_open_moved_against_the_trader():
    series = {"TEST": _flat_series(price=100.0, step=1.0)}
    p = _policy(series, slippage_bps=10.0, fee_bps=0.0)
    pos = p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=5)
    bar = MK.ExecutionFeed(series).bar("TEST", 6)
    assert pos.entry.reference_price == bar.open
    assert pos.entry.fill_price == pytest.approx(bar.open * 1.001)
    out = p.close(decision_bar=6, reason=X.CloseReason.NEURAL_SELL)
    bar7 = MK.ExecutionFeed(series).bar("TEST", 7)
    assert out.exit.reference_price == bar7.open
    assert out.exit.fill_price == pytest.approx(bar7.open * 0.999)


# ------------------------------------------------------- accounting

def test_accounting_identity_holds_and_fees_are_charged_both_sides():
    series = {"TEST": _flat_series(price=100.0, step=0.5)}
    p = _policy(series, notional=1000.0, fee_bps=5.0, slippage_bps=5.0)
    start = p.account.cash

    pos = p.open_long(episode_id=7, symbol="TEST", stable_id=3, decision_bar=4)
    assert p.account.cash == pytest.approx(
        start - pos.quantity * pos.entry.fill_price - pos.entry.fee)
    assert pos.quantity * pos.entry.fill_price == pytest.approx(1000.0)
    assert pos.entry.fee == pytest.approx(1000.0 * 5e-4)

    out = p.close(decision_bar=9, reason=X.CloseReason.NEURAL_SELL)
    assert out.fees == pytest.approx(out.entry.fee + out.exit.fee)
    assert out.gross_pnl == pytest.approx(
        out.entry.quantity * (out.exit.fill_price - out.entry.fill_price))
    assert out.net_pnl == pytest.approx(out.gross_pnl - out.fees)
    # the identity the Account checks on every close
    assert p.account.cash == pytest.approx(start + p.account.realized_pnl)
    assert p.account.position is None
    p.account.check()


def test_a_flat_tape_loses_exactly_the_costs():
    p = _policy({"TEST": _flat_series(price=100.0, step=0.0)},
                notional=1000.0, fee_bps=5.0, slippage_bps=5.0)
    p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=4)
    out = p.close(decision_bar=9, reason=X.CloseReason.POLICY_CLOSE)
    # two 5 bps fees and a 10 bps round-trip slippage on 1000 of notional
    assert out.gross_pnl < 0
    assert out.net_pnl == pytest.approx(-2.0, abs=0.01)
    assert out.return_on_notional == pytest.approx(-0.002, abs=1e-5)


def test_inventory_and_equity_track_the_open_position():
    series = {"TEST": _flat_series(price=100.0, step=1.0)}
    p = _policy(series, notional=1000.0, fee_bps=0.0, slippage_bps=0.0)
    start = p.account.cash
    assert p.account.equity() == start
    pos = p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=4)
    assert p.account.equity(mark=pos.entry.fill_price) == pytest.approx(start)
    assert p.account.equity(mark=pos.entry.fill_price * 1.1) == pytest.approx(
        start + 0.1 * 1000.0)


# ----------------------------------------------------------- policy

def test_one_open_position_and_sell_is_never_a_short():
    p = _policy({"A": _flat_series("A"), "B": _flat_series("B")})
    p.open_long(episode_id=1, symbol="A", stable_id=0, decision_bar=4)
    r = p.open_long(episode_id=2, symbol="B", stable_id=1, decision_bar=4)
    assert isinstance(r, X.Rejection)
    assert r.reason is X.RejectReason.POSITION_OPEN
    p.close(decision_bar=5, reason=X.CloseReason.NEURAL_SELL)
    r = p.close(decision_bar=6, reason=X.CloseReason.NEURAL_SELL)
    assert isinstance(r, X.Rejection)
    assert r.reason is X.RejectReason.NO_POSITION
    assert p.stats()["rejections"] == {"POSITION_OPEN": 1, "NO_POSITION": 1}


def test_horizon_expiry_is_labelled_policy_close_not_a_neural_sell():
    p = _policy(horizon_bars=8)
    pos = p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=4)
    assert pos.horizon_bar == pos.entry.bar_index + 8
    assert not p.due_for_horizon(pos.horizon_bar - 1)
    assert p.due_for_horizon(pos.horizon_bar)
    out = p.close(decision_bar=pos.horizon_bar,
                  reason=X.CloseReason.POLICY_CLOSE)
    assert out.close_reason is X.CloseReason.POLICY_CLOSE
    assert out.close_reason is not X.CloseReason.NEURAL_SELL
    assert p.stats()["close_reasons"] == {"POLICY_CLOSE": 1}


def test_running_out_of_bars_is_end_of_data_not_a_decision():
    p = _policy({"TEST": _flat_series(n=20)})
    p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=10)
    out = p.close(decision_bar=19, reason=X.CloseReason.POLICY_CLOSE)
    assert out.close_reason is X.CloseReason.END_OF_DATA
    assert out.exit.bar_index == 19


def test_a_buy_with_no_future_bar_is_rejected():
    p = _policy({"TEST": _flat_series(n=20)})
    r = p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=19)
    assert isinstance(r, X.Rejection)
    assert r.reason is X.RejectReason.NO_FUTURE_BAR
    assert p.account.position is None


def test_a_nan_bar_is_rejected_not_traded_through():
    bars = list(_flat_series().bars)
    bars[6] = MK.Bar(bars[6].ts, float("nan"), float("nan"), float("nan"),
                     float("nan"), float("nan"))
    p = _policy({"TEST": MK.Series("TEST", tuple(bars), MK.BAR_SECONDS)})
    r = p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=5)
    assert isinstance(r, X.Rejection)
    assert r.reason is X.RejectReason.BAD_PRICE


# ------------------------------------------------------ reinforcement

@pytest.mark.parametrize("net,valence,amount", [
    (+10.0, +1, 1.0),      # +1% of 1000 notional -> full strength, at the cap
    (+5.0, +1, 0.5),
    (-5.0, -1, 0.5),
    (-100.0, -1, 1.0),     # clipped at the declared cap
    (0.0, 0, 0.0),         # exactly flat delivers nothing
])
def test_reinforcement_maps_net_realised_pnl_to_a_dopamine_event(
        net, valence, amount):
    p = _policy()
    entry = X.Fill(X.Side.BUY, "TEST", 1, 0, 100.0, 100.0, 10.0, 0.0)
    out = X.OutcomeRecord(
        episode_id=1, symbol="TEST", stable_id=0, entry=entry, exit=entry,
        close_reason=X.CloseReason.POLICY_CLOSE, gross_pnl=net, fees=0.0,
        net_pnl=net, notional=1000.0, bars_held=1, market_seconds_held=3600)
    v, a = p.reinforcement(out)
    assert v == valence
    assert a == pytest.approx(amount)


def test_reinforcement_reads_realised_pnl_only():
    """An open position at a profit reinforces nothing until it is closed."""
    series = {"TEST": _flat_series(price=100.0, step=5.0)}
    p = _policy(series, fee_bps=0.0, slippage_bps=0.0)
    p.open_long(episode_id=1, symbol="TEST", stable_id=0, decision_bar=4)
    assert p.outcomes == []
    assert p.account.realized_pnl == 0.0
    assert p.account.equity(mark=200.0) > p.account.initial_cash  # unrealised
    out = p.close(decision_bar=9, reason=X.CloseReason.POLICY_CLOSE)
    assert len(p.outcomes) == 1
    assert p.reinforcement(out)[0] == +1


def test_no_counterfactual_outcome_exists_for_an_unchosen_instrument():
    p = _policy({"A": _flat_series("A"), "B": _flat_series("B", step=10.0)})
    p.open_long(episode_id=1, symbol="A", stable_id=0, decision_bar=4)
    p.close(decision_bar=9, reason=X.CloseReason.POLICY_CLOSE)
    assert [o.symbol for o in p.outcomes] == ["A"]
    assert all(o.symbol != "B" for o in p.outcomes)


def test_declared_defaults_are_the_ones_documented():
    """docs/EXECUTION.md states these; the code must agree."""
    p = _policy()
    d = p.as_dict()
    assert d["version"] == "flytrade-exec-1"
    assert d["delay_bars"] == 1
    assert d["horizon_bars"] == 8
    assert d["notional"] == 1000.0
    assert d["fee_bps"] == 5.0
    assert d["slippage_bps"] == 5.0
    assert d["reinforce_full_scale"] == 0.01
    assert d["reinforce_cap"] == 1.0
    assert math.isclose(d["initial_cash"], 10000.0)
