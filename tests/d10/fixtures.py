"""Scripted tapes and curves for the D10 loop tests. **Every number invented.**

Nothing in this module is an observation of Robinhood Chain or of PONS. The
reserves, timestamps, block numbers and trade sizes are constructed so a test
can ask for a token that is too young, one that stops trading, one whose curve
completes mid-position and one whose data runs out before its horizon — none of
which a real window supplies on demand. No figure produced here may ever be
reported as a measurement.

What is real in the tests that use it: the whole of
:mod:`flytrade.pons.context`, :mod:`flytrade.pons.admission`,
:mod:`flytrade.pons.paper` and :mod:`flytrade.pons.curve`, including the
integer-exact quote and its fee, tax and impact arithmetic.
"""

from __future__ import annotations

from flytrade.pons.collector import BlockClock
from flytrade.pons.context import TokenTape
from flytrade.pons.curve import CurveState
from flytrade.pons.seed import LAUNCH_SEED, seed_state

CHAIN_ID = 4663
NATIVE = "0x" + "0" * 40
FIRST_BLOCK = 1_000_000
FIRST_TS = 1_700_000_000
#: one block every 0.1 s, so a second is ten blocks. Invented, round, and
#: chosen only so the arithmetic in a test is readable.
INTERVAL_S = 0.1


def block_at(seconds: int) -> int:
    return FIRST_BLOCK + int(seconds * 10)


def ts_at(block: int) -> int:
    return FIRST_TS + int((block - FIRST_BLOCK) // 10)


def clock(last_seconds: int = 4_000) -> BlockClock:
    """A grid of one header per 100 blocks over ``last_seconds`` of chain time."""
    headers = []
    block = FIRST_BLOCK
    while block <= block_at(last_seconds):
        headers.append({"number": block, "timestamp": ts_at(block),
                        "hash": f"0x{block:064x}"})
        block += 100
    return BlockClock(headers, interval_s=INTERVAL_S, grid_blocks=100)


def buy_event(curve: str, *, at_seconds: int, quote_in: int, state: CurveState,
              log_index: int = 0) -> dict:
    """A ``CurveBuy`` whose numbers satisfy the curve's own arithmetic."""
    fee = quote_in * state.fee_bps // 10_000
    tax = quote_in * state.creator_tax_bps // 10_000
    net = quote_in - fee - tax
    tokens = net * state.token_reserve // (state.quote_reserve + net)
    tokens = min(tokens, state.sellable_tokens)
    block = block_at(at_seconds)
    return {
        "event": "CurveBuy", "source": "curve", "status": "OK",
        "address": curve, "curve": curve,
        "block_number": block, "block_timestamp": ts_at(block),
        "tx_index": 0, "log_index": log_index,
        "log_id": f"0x{block:064x}:0x{log_index:064x}:{log_index}",
        "args": {"buyer": "0x" + "1" * 40, "recipient": "0x" + "1" * 40,
                 "quoteIn": str(quote_in), "tokensOut": str(tokens),
                 "fee": str(fee), "tax": str(tax)},
    }


def sell_event(curve: str, *, at_seconds: int, tokens_in: int,
               state: CurveState, log_index: int = 0) -> dict:
    gross = tokens_in * state.quote_reserve // (state.token_reserve + tokens_in)
    fee = gross * state.fee_bps // 10_000
    tax = gross * state.creator_tax_bps // 10_000
    block = block_at(at_seconds)
    return {
        "event": "CurveSell", "source": "curve", "status": "OK",
        "address": curve, "curve": curve,
        "block_number": block, "block_timestamp": ts_at(block),
        "tx_index": 0, "log_index": log_index,
        "log_id": f"0x{block:064x}:0x{log_index:064x}:{log_index}",
        "args": {"seller": "0x" + "2" * 40, "recipient": "0x" + "2" * 40,
                 "tokensIn": str(tokens_in), "quoteOut": str(gross - fee - tax),
                 "fee": str(fee), "tax": str(tax)},
    }


def completed_event(curve: str, *, at_seconds: int, log_index: int = 9) -> dict:
    block = block_at(at_seconds)
    return {
        "event": "CurveCompleted", "source": "curve", "status": "OK",
        "address": curve, "curve": curve,
        "block_number": block, "block_timestamp": ts_at(block),
        "tx_index": 0, "log_index": log_index,
        "log_id": f"0x{block:064x}:0x{log_index:064x}:{log_index}",
        "args": {"recipient": "0x" + "3" * 40, "quoteOut": "0", "tokenOut": "0"},
    }


def tape(*, token: str = "0x" + "a" * 40, curve: str = "0x" + "b" * 40,
         creator_tax_bps: int = 200, coverage_seconds: int = 4_000) -> TokenTape:
    """A freshly launched curve at the pinned seed. No trades yet."""
    return TokenTape(
        token=token, curve=curve, launch_block=FIRST_BLOCK,
        launched_at=FIRST_TS, initial=seed_state(creator_tax_bps),
        snipe_start_bps=int(LAUNCH_SEED["snipe_start_bps"]),
        snipe_window_seconds=int(LAUNCH_SEED["snipe_window_seconds"]),
        quote_asset=NATIVE, deployment="pons-v2",
        coverage_end_ts=ts_at(block_at(coverage_seconds)))


def traded_tape(trades=((10, 5 * 10 ** 16), (40, 3 * 10 ** 16),
                        (80, 7 * 10 ** 16), (130, 2 * 10 ** 16)),
                **kw) -> TokenTape:
    """A tape with buys at the given ``(second, quote in wei)`` points."""
    tp = tape(**kw)
    for i, (second, quote) in enumerate(trades):
        tp.apply(buy_event(tp.curve, at_seconds=second, quote_in=quote,
                           state=tp.state, log_index=i))
    return tp
