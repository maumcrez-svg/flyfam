"""
The target-alignment audit — §8, Fable addendum 11, and §9's bankroll test.

The audit compares two numbers per episode: the outcome the fly was actually
reinforced on, and the fixed-90-minute outcome D7's evaluation scored. Three
things have to hold for that comparison to mean anything, and each is tested
here: the chains are grouped from the log as written; the hypothetical hold
starts from the *same* entry the episode actually got; and no part of it can
reach an account.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

import alignment as AL                               # experiments/d8
from flytrade import horizon as HZ
from flytrade import records as REC

ROOT = Path(__file__).resolve().parents[2]
D8 = ROOT / "experiments" / "d8"
AUDIT = json.loads((D8 / "alignment.json").read_text())
S = AUDIT["summary"]


# ------------------------------------------------- the parser, on a fixture

def test_chains_group_by_episode_inside_the_named_partition(tmp_path):
    """Events outside the partition, and chains without an OUTCOME, are out."""
    p = tmp_path / "events.jsonl"
    lines = [
        {"kind": "PARTITION", "partition": "WARMUP", "boundary": "start"},
        {"kind": "DECISION", "episode_id": 1, "bar_index": 5},
        {"kind": "PARTITION", "partition": "WARMUP", "boundary": "end"},
        {"kind": "PARTITION", "partition": "LEARNING", "boundary": "start"},
        {"kind": "DECISION", "episode_id": 7, "bar_index": 9},
        {"kind": "EXECUTION", "episode_id": 7, "bar_index": 10},
        {"kind": "OUTCOME", "episode_id": 7, "close_reason": "NEURAL_SELL"},
        {"kind": "LEARNING", "episode_id": 7, "valence": -1},
        {"kind": "DECISION", "episode_id": 8, "bar_index": 20},   # never filled
        {"kind": "PARTITION", "partition": "LEARNING", "boundary": "end"},
        {"kind": "DECISION", "episode_id": 9, "bar_index": 30},
        {"kind": "OUTCOME", "episode_id": 9},
    ]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    got = AL.chains(p, "LEARNING")
    assert set(got) == {7}
    assert set(got[7]) == {"DECISION", "EXECUTION", "OUTCOME", "LEARNING"}


def test_the_audit_parses_through_flytrade_records():
    assert AUDIT["parser"] == "flytrade.records.EventLog.read"
    assert hasattr(REC.EventLog, "read")


# ----------------------------------------- the hypothetical, on a fixture

def test_the_hypothetical_hold_starts_at_the_same_bar_the_policy_would(clean):
    """Same convention, same delay: entry is the open at decision + 1 minute."""
    from tests.d8 import make_fixtures as MF
    day = MF.DAYS[1]
    for m in (30, 120, 200):
        h = HZ.hold(clean, day, m, 90, delay=1)
        assert h.ok
        assert h.entry_minute == m + 1
        assert h.exit_minute == h.entry_minute + 90
        assert h.entry_open == clean.bar(day, m + 1).open


def test_the_net_return_is_the_settlement_arithmetic_not_a_new_formula(clean):
    from tests.d8 import make_fixtures as MF
    day = MF.DAYS[1]
    h = HZ.hold(clean, day, 100, 90, delay=1)
    notional, fee, slip = 1000.0, 5.0, 5.0
    s, f = slip * 1e-4, fee * 1e-4
    entry_fill = h.entry_open * (1.0 + s)
    exit_fill = h.exit_open * (1.0 - s)
    qty = notional / entry_fill
    gross = qty * (exit_fill - entry_fill)
    fees = abs(qty * entry_fill) * f + abs(qty * exit_fill) * f
    assert abs(h.net_pnl(notional=notional, fee_bps=fee, slippage_bps=slip)
               - (gross - fees)) < 1e-9


def test_an_unavailable_hypothetical_is_named_never_replaced_by_a_loss(clean):
    from tests.d8 import make_fixtures as MF
    day = MF.DAYS[1]
    h = HZ.hold(clean, day, 380, 90, delay=1)          # past the clock rule
    assert not h.ok and h.reason == "SESSION_HORIZON"


# ------------------------------------------------- the committed artifact

def test_the_hypothetical_entry_equals_the_actual_entry_on_every_episode():
    e = S["entry_fill_identity"]
    assert e["compared"] == 42
    assert e["reference_price_equal"] == 42
    assert e["slipped_fill_equal"] == 42
    assert e["max_abs_diff"] == 0.0


def test_every_episode_carries_the_columns_section_8_lists():
    need = ("information_cutoff", "entry_time", "actual_exit_time",
            "actual_exit_reason", "actual_holding_minutes",
            "actual_gross_pnl", "actual_net_pnl", "reinforcement_sign",
            "hypothetical_H90")
    assert len(AUDIT["episodes"]) == 42
    for r in AUDIT["episodes"]:
        for k in need:
            assert k in r, k
        assert r["hypothetical_H90"]["available"] in (True, False)
        if r["hypothetical_H90"]["available"]:
            assert r["hypothetical_H90"]["label_Y"] in (0, 1)


def test_the_reinforcement_sign_is_the_recorded_valence_not_a_recomputation():
    for r in AUDIT["episodes"]:
        assert r["reinforcement_sign"] in (1, -1)
        assert r["reinforcement_accepted"] is True
        # in this run the recorded valence happens to agree with sign(net);
        # the audit reports both columns rather than collapsing them
        assert r["actual_sign"] in (1, -1)


def test_the_costs_reconcile_with_the_recorded_accounting():
    c = S["costs"]
    assert abs((c["total_gross_reference_pnl"] - c["total_fees"]
                - c["total_slippage"]) - c["total_net_pnl"]) < 1e-6
    assert c["executions"] == 2 * S["episodes"]
    assert c["round_trip_bps_nominal"] == 20.0


def test_the_sign_comparison_adds_up():
    sc = S["sign_comparison"]
    assert sc["agree"] + sc["disagree"] == sc["compared"]
    assert abs(sc["proportion_disagreeing"]
               - sc["disagree"] / sc["compared"]) < 1e-12
    d = sc["disagreements_by_actual_sign"]
    a = sc["agreements_by_actual_sign"]
    assert d["actual_positive"] + d["actual_negative"] == sc["disagree"]
    assert a["actual_positive"] + a["actual_negative"] == sc["agree"]
    assert (d["actual_positive"] + a["actual_positive"]
            == S["actual_sign_counts"]["positive"])


def test_every_exit_was_a_neural_sell_before_the_horizon():
    assert S["exits_before_H"] == 42
    assert S["exits_at_or_after_H"] == 0
    assert S["exit_reasons"] == {"NEURAL_SELL": 42}
    assert S["holding_minutes"]["max"] < S["H"]


def test_no_hypothetical_outcome_is_booked_anywhere():
    """§8: not a portfolio PnL, not a reward, not an account."""
    text = json.dumps(AUDIT)
    for forbidden in ("cash", "bankroll", "equity", "realized_pnl",
                      "hypothetical_total_pnl", "hypothetical_portfolio"):
        assert forbidden not in text, forbidden
    assert "NOT summed into a portfolio PnL" in S["hypothetical_totals_note"]
    assert "not booked anywhere" in S["hypothetical_totals_note"]
    assert "do not simulate the trades a fixed-hold policy would have taken" \
        in AUDIT["caveat"]
    assert "never booked as portfolio PnL" in AUDIT["forbidden"]


def test_the_audit_states_that_it_measures_alignment_not_success():
    assert "measures alignment" in AUDIT["caveat"]
    assert "not whether fixed-hold training would succeed" in AUDIT["caveat"]
    assert "no weight update" in AUDIT["forbidden"]
    md = (D8 / "alignment.md").read_text()
    assert "not** simulate the trades a fixed-hold policy" in md
    assert "booked as portfolio PnL" in md


def test_the_original_cost_constants_were_used():
    c = AUDIT["costs_used"]
    assert (c["notional"], c["fee_bps"], c["slippage_bps"]) == (1000.0, 5.0, 5.0)
    assert AUDIT["H"] == 90 and AUDIT["delay_minutes"] == 1
