"""
The observer's four D7 additions — amendment §10.

"Reuse the local observer. Add only: selected H and calibration provenance;
actual versus hypothetical/probe labels; current phase and historical
timestamp; final context-discrimination summary after evaluation. Do not
reveal a future probe label during earlier playback. Do not build a new
frontend."

These tests hold the page to exactly that: the four additions are present, the
page is still vanilla and still computes nothing, the server still only reads,
and the two objects that are *future* relative to the replay — a probe's label
and the final summary — are sealed behind the replay cursor rather than
displayed from the start.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "observer"
sys.path.insert(0, str(OBSERVER))

import serve as SRV                    # noqa: E402


def page() -> str:
    return (OBSERVER / "index.html").read_text()


# ------------------------------------------------------------- the server

def test_the_server_serves_both_waves_from_their_own_directories():
    waves = {r["wave"]: r for r in SRV.ROOTS}
    # D9(b) added a third root by the same mechanism; what this test protects
    # is that D5/D6 and D7 keep their own directories, not that no later wave
    # may ever register one.
    assert {"D5/D6", "D7"} <= set(waves)
    assert SRV.ROOTS[0]["wave"] == "D5/D6" and SRV.ROOTS[1]["wave"] == "D7"
    assert waves["D7"]["runs"] == ROOT / "experiments" / "d7" / "runs"
    assert waves["D7"]["summary"] == \
        ROOT / "experiments" / "d7" / "frozen_summary.json"
    assert waves["D5/D6"]["runs"] == \
        ROOT / "experiments" / "historical" / "runs"


def test_the_d7_artifacts_are_the_committed_read_only_files():
    extra = {r["wave"]: r["extra"] for r in SRV.ROOTS}["D7"]
    assert set(extra) == {"horizon", "context", "probes", "learning"}
    for p in extra.values():
        assert p.parent == ROOT / "experiments" / "d7"


def test_an_unknown_run_id_falls_back_and_never_escapes_the_roots():
    assert SRV.root_for("") is SRV.ROOTS[0]
    assert SRV.root_for("../../etc") is SRV.ROOTS[0]


def test_the_server_still_only_reads_and_still_binds_to_loopback():
    src = (OBSERVER / "serve.py").read_text()
    assert SRV.HOST == "127.0.0.1" and "0.0.0.0" not in src
    assert ".write_text(" not in src and ".write_bytes(" not in src
    assert "do_POST" not in src and "do_PUT" not in src
    # the artifact route hands a file over unchanged, like every other route
    assert 'return self._send(200, p.read_bytes(), "application/json")' in src


# --------------------------------------------------------- the four additions

def test_addition_one_the_selected_horizon_and_its_provenance():
    h = page()
    assert 'id="sec-horizon"' in h
    for field in ("h-star", "h-cost", "h-thr", "h-win", "h-ses", "h-art",
                  "h-table"):
        assert f'id="{field}"' in h, field
    assert "round_trip_cost_bps_measured" in h
    assert "Not a forecast of" in h or "not a claim that returns" in h


def test_addition_two_actual_versus_hypothetical_is_marked_on_the_page():
    h = page()
    assert 'class="tag actual"' in h and 'class="tag hypo"' in h
    # the three money panels are actual; the probe panel is hypothetical
    assert h.count('class="tag actual"') >= 3
    assert 'id="sec-probe"' in h and 'class="hyp"' in h
    assert "no order, no learning event" in h
    assert "never added to any other probe" in h


def test_addition_three_the_phase_and_the_historical_instant():
    h = page()
    assert 'id="phase"' in h and 'id="when"' in h
    assert "function renderPhase(" in h
    assert "st.partition.partition" in h


def test_addition_four_the_summary_comes_after_the_evaluation():
    h = page()
    assert 'id="sec-context"' in h
    for field in ("cx-verdict", "cx-delta", "cx-levels", "cx-q", "cx-cov",
                  "cx-boot", "cx-mp", "cx-table", "cx-why"):
        assert f'id="{field}"' in h, field
    assert "day-resampled" in h.lower()
    assert "no trading skill is claimed" in h


def test_no_future_probe_label_is_revealed_during_earlier_playback():
    """The label appears only once the replay passes its exit bar's bar_end."""
    h = page()
    assert "const revealed = !!(pr && mt && mt >= pr.exit_ts + 60);" in h
    assert 'sealed until "+tsNY(pr.exit_ts+60)' in h
    # the only label ever shown is one whose exit price has already printed
    assert "if(row.exit_ts + 60 <= mt) m = row; else break;" in h
    # and the final summary is sealed until the cursor reaches the end
    assert "const atEnd = EV.length>0 && I >= EV.length-1;" in h
    assert '$("cx-body").hidden = !atEnd;' in h


def test_the_page_is_still_vanilla_and_still_builds_nothing():
    h = page()
    assert "<script src=" not in h
    assert "https://" not in h
    assert "http://" not in h.replace("http://127.0.0.1", "")
    for framework in ("react", "vue", "angular", "jquery", "import ",
                      "require("):
        assert framework not in h.lower(), framework
    assert not (OBSERVER / "package.json").exists()


def test_the_page_still_recomputes_no_decision_and_no_money():
    h = page()
    for forbidden in ("BASELINE", "theta_sd", "0.9117", "gross - fees",
                      "+= e.net_pnl", "reduce((a,e)=>a+e.net"):
        assert forbidden not in h, forbidden
    # the probe label is read off the probe row; the page does not price it
    assert "pr.G" in h and "entry_open" not in h and "exit_open" not in h
    assert "method:" not in h and "POST" not in h


def test_the_probe_panel_reads_the_score_the_run_recorded():
    """The score on the page is the log's own V, not a re-decoded one."""
    h = page()
    assert "pr.v_reference" in h and "pr.v_trained" in h
    assert "the decoder's own\n      recorded V" in h or \
        "recorded V for this round" in h


def test_the_committed_artifacts_if_present_have_the_fields_the_page_reads():
    d7 = ROOT / "experiments" / "d7"
    art = d7 / "registered-horizon-artifact"
    if art.exists():
        a = json.loads(art.read_text())
        for k in ("selected_horizon_minutes", "threshold_bps", "A_bps",
                  "cost", "window", "n_qualifying", "config_sha256"):
            assert k in a, k
        assert "round_trip_cost_bps_measured" in a["cost"]
    ctx = d7 / "context_summary.json"
    if ctx.exists():
        c = json.loads(ctx.read_text())
        for k in ("delta_auc", "sessions", "bootstrap", "coverage",
                  "matched_participation", "conclusion", "dependence"):
            assert k in c, k
    probes = d7 / "withheld-probe-table"
    if probes.exists():
        p = json.loads(probes.read_text())
        assert p["rows"] == [] or set(
            ("market_ts", "v_trained", "v_reference", "G", "Y", "exit_ts",
             "entry_minute", "exit_minute")) <= set(p["rows"][0])
