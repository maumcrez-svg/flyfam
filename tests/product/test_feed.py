"""The feed: one SNIFF a tick, one heartbeat a tick, and a state file that says.

P1 addendum 4. The two files are the whole contract the spectacle reads, and
``docs/SPECTACLE_FEED.md`` is where it is written down; the last test in this
module asserts that the document and the file agree in both directions, so the
contract cannot drift away from what the loop writes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from flytrade import records as REC
from flytrade.product import feed as FEED
from tests.product import harness as H

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "SPECTACLE_FEED.md"

#: every key ``state.json`` carries. The document names each of them; the test
#: at the bottom compares the two lists in both directions.
STATE_KEYS = {
    "version", "run_id", "venue", "chain_id", "mode", "learning", "data",
    "execution", "updated_epoch", "updated_utc", "day_file", "seq", "kinds",
    "brain", "account", "position", "last_pick", "events", "episodes",
    "biggest_win", "biggest_loss", "rejected", "sniffed", "credits",
    "requests", "health", "restore",
}


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("feed")
    head = 1_000
    logs = [H.pinned_launch(head + 2)] + H.trades(head + 5, 200, every=10)
    built = H.stack(tmp, logs=logs, head=head,
                    decoder=H.ScriptedDecoder(None, buys=1))
    H.stop_after(built, 40)
    out = built["loop"].run_branch()
    return built, out, H.read_events(built), H.read_state(built)


def test_one_sniff_per_tick_and_never_one_per_candidate(ran):
    built, out, events, state = ran
    sniffs = [e for e in events if e["kind"] == "SNIFF"]
    assert len(sniffs) == out["ticks"] == built["driver"].ticks_done
    # the candidates are a list *inside* the event, with their outcome
    seen = [s for s in sniffs if s["candidates"]]
    assert seen, "no tick saw a candidate at all"
    for row in seen[0]["candidates"]:
        assert set(row) == {"token", "admitted", "reasons"}
    # the rows are capped and ordered; the counts and the histogram are not
    assert seen[0]["candidates_listed"] == len(seen[0]["candidates"])
    assert (seen[0]["considered"]
            == seen[0]["candidates_listed"] + seen[0]["candidates_truncated"])
    assert seen[0]["candidates_listed"] <= 250
    assert seen[0]["admitted"] + seen[0]["rejected"] == seen[0]["considered"]
    assert set(seen[0]) >= {"tracked", "considered", "admitted", "presented",
                            "rotated", "rejected", "reasons", "holding"}


def test_every_tick_writes_exactly_one_heartbeat(ran):
    built, out, events, state = ran
    beats = [e for e in events if e["kind"] == "HEARTBEAT"]
    assert len(beats) == out["ticks"]
    for key in ("uptime_s", "requests", "account", "position", "head_block",
                "cursor_block", "tracked", "errors", "throttled",
                "brain_digest", "rss_mib", "episodes"):
        assert key in beats[-1], key
    assert beats[-1]["requests"]["hour_cap"] == built["cfg"]["limits"][
        "hourly_request_cap"]
    assert beats[-1]["brain_digest"] == built["digest"]


def test_the_kinds_are_the_nine_and_they_are_canonical_event_types(ran):
    built, out, events, state = ran
    kinds = {e["kind"] for e in events}
    assert kinds <= set(FEED.KINDS)
    assert kinds >= {"SNIFF", "PICK", "OPEN", "MARK", "CLOSE", "CREDIT",
                     "HEARTBEAT"}
    canonical = {e.value for e in REC.EventType}
    assert set(FEED.KINDS) <= canonical
    assert len(FEED.KINDS) == 9


def test_every_event_carries_the_stamp_and_a_monotone_sequence(ran):
    built, out, events, state = ran
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    for e in events[:50]:
        assert e["venue"] == "PONS" and e["chain_id"] == 4663
        assert e["mode"] == "LIVE_PAPER" and e["learning"] == "FROZEN"
        assert e["data"] == "LIVE" and e["execution"] == "PAPER"
        assert e["run_id"] == built["cfg"]["run_id"]
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", e["utc"])


def test_the_day_file_is_named_for_the_utc_day(ran):
    built, out, events, state = ran
    names = sorted(p.name for p in Path(built["paths"]["dir"]).glob("events-*.jsonl"))
    assert names
    for name in names:
        assert re.fullmatch(r"events-\d{4}-\d\d-\d\d\.jsonl", name)
    assert state["day_file"] in names
    # a second day writes a second file and rewrites nothing
    feed = built["feed"]
    day_two = FEED.day_file(built["paths"]["dir"], feed._now() + 86_400)
    assert day_two.name not in names


def test_state_json_is_rewritten_after_every_event(ran):
    built, out, events, state = ran
    assert state["seq"] == events[-1]["seq"] == built["feed"].seq
    assert state["events"][-1] == built["feed"]._for_state(events[-1])
    assert len(state["events"]) <= built["cfg"]["feed"]["keep_events_in_state"]
    # and it is a whole document every time: the write is temp-rename
    again = json.loads(Path(built["paths"]["state"]).read_text())
    assert again == state


def test_state_json_carries_every_documented_key(ran):
    built, out, events, state = ran
    assert set(state) == STATE_KEYS
    assert state["version"] == FEED.STATE_VERSION
    assert state["brain"]["digest"] == built["digest"]
    assert state["brain"]["learning"] == "FROZEN"
    assert state["brain"]["credit_recorded_never_applied"] is True
    for key in ("cash_eth", "cash_wei", "realized_pnl_eth", "realized_pnl_wei",
                "unrealised_eth", "equity_eth", "fees_paid_eth", "trades",
                "initial_cash_eth", "size_eth"):
        assert key in state["account"], key
    for key in ("hour", "hour_cap", "total_attempts", "total_units",
                "by_method", "backfill"):
        assert key in state["requests"], key
    for key in ("uptime_s", "ticks_this_process", "tick", "last_cutoff_ts",
                "throttled", "errors", "reorgs", "brain_digest", "learning",
                "stop", "tracked_curves"):
        assert key in state["health"], key
    assert set(state["rejected"]) == {"session", "last_hour"}
    assert set(state["sniffed"]) >= {"ticks", "candidates", "admitted",
                                     "rejected", "picked", "last_tick"}


def test_the_state_window_drops_only_the_candidate_rows(ran):
    """A half-megabyte file rewritten ten times a tick is not a contract."""
    built, out, events, state = ran
    day = {e["seq"]: e for e in events}
    for kept in state["events"]:
        whole = day[kept["seq"]]
        if kept["kind"] != "SNIFF" or not whole.get("candidates"):
            assert kept == whole
            continue
        assert kept["candidates"] == []
        assert kept["candidates_in_the_day_file"] == len(whole["candidates"])
        assert kept["candidates_listed"] == whole["candidates_listed"]
        assert kept["reasons"] == whole["reasons"]
        assert {k: v for k, v in kept.items()
                if k not in ("candidates", "candidates_in_the_day_file")} == {
            k: v for k, v in whole.items() if k != "candidates"}


def test_the_last_pick_is_the_brain_snapshot(ran):
    built, out, events, state = ran
    pick = state["last_pick"]
    assert pick["kind"] == "PICK"
    for key in ("token", "action", "valence_hz", "approach_hz", "avoid_hz",
                "theta_hz", "mbon_rates_hz", "kc_active", "kc_fraction", "k",
                "replicate_scores", "brain_digest", "readout_status"):
        assert key in pick, key
    assert pick["k"] == 8
    assert len(pick["replicate_scores"]) == 8
    assert set(pick["mbon_rates_hz"]) == {"approach", "avoid"}
    assert pick["brain_digest"] == built["digest"]
    assert pick["context"] in ("FLAT", "HELD")


def test_the_position_and_its_mark_are_in_the_state_while_it_is_open(ran):
    built, out, events, state = ran
    opened = [e for e in events if e["kind"] == "OPEN"]
    marks = [e for e in events if e["kind"] == "MARK"]
    assert opened and marks
    for key in ("token", "episode_id", "entry_block", "entry_ts",
                "entry_fill_price", "quantity", "tokens_out_wei", "fee_eth",
                "horizon_ts", "size_eth"):
        assert key in opened[0], key
    for key in ("available", "mark_value_eth", "cost_eth", "unrealised_eth",
                "marginal_price"):
        assert key in marks[0], key


def test_the_episode_history_carries_the_credit_label(ran):
    built, out, events, state = ran
    assert len(state["episodes"]) == len(out["episodes"])
    row = state["episodes"][0]
    for key in ("episode_id", "token", "entry_ts", "exit_ts", "seconds_held",
                "gross_pnl_eth", "fees_eth", "net_pnl_eth", "net_pnl_wei",
                "close_reason", "settlement", "credit"):
        assert key in row, key
    assert row["credit"]["applied"] is False
    assert row["credit"]["label"] in ("REWARD", "PUNISHMENT", "NEUTRAL")
    assert row["settlement"] == "SETTLED_FROZEN"


def test_the_extremes_are_the_biggest_win_and_the_biggest_loss(ran):
    built, out, events, state = ran
    nets = [e["net_pnl"] for e in out["episodes"]]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    if wins:
        assert state["biggest_win"]["net_pnl_eth"] == max(wins)
    else:
        assert state["biggest_win"] is None
    if losses:
        assert state["biggest_loss"]["net_pnl_eth"] == min(losses)
    else:
        assert state["biggest_loss"] is None


def test_the_rejected_counts_are_the_sniff_reasons(ran):
    built, out, events, state = ran
    from collections import Counter
    counted = Counter()
    for e in events:
        if e["kind"] == "SNIFF":
            counted.update(e.get("reasons") or {})
    assert dict(counted) == state["rejected"]["session"]


def test_the_documented_contract_and_the_state_file_agree(ran):
    """Every key in the file is in the document, and the reverse."""
    built, out, events, state = ran
    text = DOC.read_text()
    for key in sorted(STATE_KEYS):
        assert f"`{key}`" in text, f"{key} is not documented"
    for kind in FEED.KINDS:
        assert f"`{kind}`" in text, f"{kind} is not documented"
    section = text[text.index("## 3. `state.json`"):text.index("## 4.")]
    missing = {k for k in STATE_KEYS if f"`{k}`" not in section}
    assert not missing, f"undocumented in the state.json section: {missing}"
    # and the other way: the section names no key the file does not carry
    named = set(re.findall(r"`([a-z_]+)`", section.split("\n| `restore` |")[0]))
    assert named & STATE_KEYS == STATE_KEYS - {"restore"}
