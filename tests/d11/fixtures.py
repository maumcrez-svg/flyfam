"""Scripted tapes for the D11 tests. **Every number invented.**

Built on :mod:`tests.d10.fixtures`, whose disclaimer applies unchanged: nothing
here is an observation of Robinhood Chain or of PONS, and no figure produced by
this module may ever be reported as a measurement. The reserves, timestamps and
trade sizes are constructed so a test can ask for a token that traded two
seconds ago, one that traded four minutes ago, one whose buys and sells cancel,
and one whose log is duplicated — none of which a real window supplies on
demand.

What is real in the tests that use it: the whole of
:mod:`flytrade.pons.context_v2`, :mod:`flytrade.pons.admission_v2`,
:mod:`flytrade.pons.encoder_v2`, :mod:`flytrade.pons.curve` and
:mod:`flytrade.execution`, including the integer-exact quote.
"""

from __future__ import annotations

from flytrade.pons.context import TokenTape

from tests.d10.fixtures import (CHAIN_ID, FIRST_BLOCK, FIRST_TS,  # noqa: F401
                                INTERVAL_S, NATIVE, block_at, buy_event, clock,
                                completed_event, sell_event, tape, ts_at)

#: one quote unit that is comfortably above the fee floor and below the curve's
#: capacity, so a scripted trade is always a *valid* trade.
QUOTE = 5 * 10 ** 16


def traded_at(seconds, *, quotes=None, sells=(), **kw) -> TokenTape:
    """A tape whose buys land at the given ``seconds`` after the launch.

    ``sells`` names the seconds that should be a sell instead of a buy, so a
    test can make the two sides symmetric without restating the arithmetic.
    """
    tp = tape(**kw)
    for i, second in enumerate(seconds):
        quote = QUOTE if quotes is None else quotes[i]
        if second in sells:
            tokens = tp.state.sellable_tokens // 200
            tp.apply(sell_event(tp.curve, at_seconds=second,
                                tokens_in=tokens, state=tp.state, log_index=i))
        else:
            tp.apply(buy_event(tp.curve, at_seconds=second, quote_in=quote,
                               state=tp.state, log_index=i))
    return tp


def active_tape(**kw) -> TokenTape:
    """Two trades inside the last two minutes, the last one 10 s ago.

    Read at ``launched_at + 300``: trades at 190 s and 290 s.
    """
    return traded_at((20, 60, 190, 290), **kw)


def quiet_tape(**kw) -> TokenTape:
    """Traded early and then went silent. Read at ``launched_at + 300``."""
    return traded_at((20, 40, 60), **kw)


def flat_but_busy_tape(**kw) -> TokenTape:
    """Many trades in the window whose buys and sells cancel out.

    Alternating buys and sells of the same notional, so ``trade_count_2m`` and
    ``gross_volume_2m`` are large while ``flow_imb_2m`` is small.
    """
    seconds = tuple(range(200, 296, 6))
    return traded_at(seconds, sells=set(seconds[1::2]), **kw)


def duplicate_of(tape_obj: TokenTape, event: dict) -> dict:
    """The same log, delivered twice. Same ``log_id``, nothing else changed."""
    return dict(event)
