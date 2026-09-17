"""The launch state is derived, not read — and this is the measurement.

`flytrade/pons/seed.py` claims two arithmetic facts, and reviewer decision 1
asks dispatch 2 to establish them on **all 546** donor calibrations before
deciding to derive instead of reading:

1. the pre-trade state of a pinned-config launch is a constant plus the
   creator tax, and the recorded launch-block state is that constant advanced
   by the launch block's own logged trades;
2. the creator tax is uniquely recoverable from one trade.

These are not fixtures. The dataset is
``data/pons/d10-replay-v1``, the donor's own hash-anchored evidence. If it is
not on disk the test skips and says so.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from flytrade.pons.curve import BPS, CurveReconstruction
from flytrade.pons.seed import (LAUNCH_SEED, creator_tax_from_trade,
                                matches_pinned_config, seed_state)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data" / "pons" / "d10-replay-v1"


@pytest.fixture(scope="module")
def donor():
    if not (DATASET / "initial_states.json").exists():
        pytest.skip(f"{DATASET} is not on disk; see data/MANIFEST.md")
    initials = json.loads((DATASET / "initial_states.json").read_text())
    by_curve = collections.defaultdict(list)
    launches = {}
    with open(DATASET / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            event = json.loads(line)
            if event.get("source") == "curve":
                by_curve[event["address"]].append(event)
            elif event.get("event") == "TokenLaunched":
                launches[event["token"]] = event
    for events in by_curve.values():
        events.sort(key=lambda e: (e["block_number"], e["tx_index"],
                                   e["log_index"]))
    return initials, by_curve, launches


def test_every_native_launch_carries_the_pinned_config(donor):
    initials, _, launches = donor
    assert len(initials) == 546
    for token in initials:
        args = launches[token]["args"]
        assert matches_pinned_config(args["launchConfigId"],
                                     args["graduationThreshold"])


def test_the_recorded_state_is_the_seed_advanced_by_the_launch_blocks_trades(donor):
    """546 of 546. This is what makes deriving it exact rather than convenient."""
    initials, by_curve, _ = donor
    checked = 0
    for token, meta in sorted(initials.items()):
        recorded = meta["state"]
        state = seed_state(int(recorded["creator_tax_bps"]))
        recon = CurveReconstruction(
            state, launch_block=meta["launch_block"],
            launched_at=meta["launched_at"],
            snipe_start_bps=meta["snipe_start_bps"],
            snipe_window_seconds=meta["snipe_window_seconds"])
        for event in by_curve.get(meta["curve"], []):
            if event["block_number"] == meta["launch_block"]:
                recon.apply(event)
        got = recon.state
        assert got.quote_reserve == int(recorded["quote_reserve"]), token
        assert got.token_reserve == int(recorded["token_reserve"]), token
        assert got.real_quote_reserve == int(recorded["real_quote_reserve"]), token
        assert got.sellable_tokens == int(recorded["sellable_tokens"]), token
        checked += 1
    assert checked == 546


def test_the_creator_tax_is_uniquely_recoverable_from_the_first_trade(donor):
    """489 of the 489 tokens that traded, 0 wrong, 57 that never traded."""
    initials, by_curve, _ = donor
    recovered = wrong = no_trade = 0
    for token, meta in sorted(initials.items()):
        trades = [e for e in by_curve.get(meta["curve"], [])
                  if e["event"] in ("CurveBuy", "CurveSell")]
        if not trades:
            no_trade += 1
            continue
        got = creator_tax_from_trade(trades[0])
        if got == int(meta["state"]["creator_tax_bps"]):
            recovered += 1
        else:
            wrong += 1
    assert wrong == 0
    assert recovered == 489
    assert no_trade == 57
    assert recovered + wrong + no_trade == 546


def test_a_token_that_never_traded_can_never_be_admitted_anyway(donor):
    """Which is why its state is left unavailable rather than paid for."""
    from flytrade.pons.context import MIN_TRADES
    initials, by_curve, _ = donor
    silent = [m for m in initials.values()
              if not [e for e in by_curve.get(m["curve"], [])
                      if e["event"] in ("CurveBuy", "CurveSell")]]
    assert silent
    for meta in silent:
        trades = [e for e in by_curve.get(meta["curve"], [])
                  if e["event"] in ("CurveBuy", "CurveSell")]
        assert len(trades) < MIN_TRADES


def test_an_ambiguous_tax_is_not_guessed():
    """A quote too small to pin the bps returns ``None``, not a best guess."""
    tiny = {"event": "CurveBuy", "args": {"quoteIn": "3", "tokensOut": "1",
                                          "fee": "0", "tax": "0"}}
    assert creator_tax_from_trade(tiny) is None
    exact = {"event": "CurveBuy",
             "args": {"quoteIn": str(10 ** 16), "tokensOut": "1",
                      "fee": "0", "tax": str(10 ** 16 * 200 // BPS)}}
    assert creator_tax_from_trade(exact) == 200


def test_a_non_trade_event_pins_nothing():
    assert creator_tax_from_trade({"event": "FeesSwept", "args": {}}) is None


def test_the_seed_is_recorded_with_its_provenance():
    assert LAUNCH_SEED["measured_on"].startswith("546 of 546")
    assert LAUNCH_SEED["graduation_threshold"] == 4_200_000_000_000_000_000
    assert seed_state(200).creator_tax_bps == 200
    assert seed_state(0).real_quote_reserve == 0
