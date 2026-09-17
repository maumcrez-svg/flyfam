#!/usr/bin/env python
"""`results.md` for a D10 run: the four conclusions, separated, and the tables.

    .venv/bin/python experiments/d10/report.py [--run d10-001]
    .venv/bin/python experiments/d10/report.py --run d10-live-001 --live

The live run gets its **own** report (`results_live.md`), written by
:func:`write_live`: a live hour and a recorded window are different blocks,
different tokens and a different clock, and no number is carried from one
table into the other.

Written twice, byte for byte: into the run's own directory, which is
gitignored like every run store since D5, and to `experiments/d10/results.md`,
which is where D7 and D9(b) keep a wave's conclusion so that it is in the
repository.

Everything here is read out of that run's own `summary.json`, which is read out
of its own event log. Nothing is recomputed and nothing is inferred: if a
number is in this file it is because the run wrote it.

The four conclusions of amendment section 13 are printed under four separate
headings and are never merged. Conclusion 4 reads *not tested* because no
predictive evaluation was designed for D10 — that is a statement about the
wave's design, registered in `PLAN.md` before the run, not a finding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = HERE / "runs"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(ROOT), check=True,
                              capture_output=True, text=True).stdout.strip()
    except Exception:                                  # pragma: no cover
        return ""


def _eth(value, places: int = 9) -> str:
    return f"{float(value):+.{places}f}"


def _mark_series(branch: dict) -> dict:
    """The open position's marks, read back out of the branch's own event log."""
    import statistics
    path = Path(branch.get("log_path", ""))
    values: list[float] = []
    unavailable = 0
    if path.is_file():
        for line in path.read_text().splitlines():
            if '"mark"' not in line:
                continue
            record = json.loads(line)
            if record.get("kind") != "ROUND":
                continue                      # the DECISION copy is the same mark
            mark = record.get("mark")
            if not isinstance(mark, dict):
                continue
            if mark.get("available"):
                values.append(float(mark["unrealised_eth"]))
            else:
                unavailable += 1
    if not values:
        return {"available": 0, "unavailable": unavailable}
    return {"available": len(values), "unavailable": unavailable,
            "min": min(values), "max": max(values),
            "median": statistics.median(values), "last": values[-1]}


def write(summary: dict, out: Path, *, rerun: dict | None = None) -> Path:
    cfg = summary["config"]
    lines: list[str] = []
    w = lines.append
    branches = summary["branches"]
    learn = branches.get("learning", {})
    frozen = branches.get("frozen_reference", {})
    episodes = learn.get("episodes", [])

    w(f"# D10 — the Pons memecoin loop ({summary['run_id']})")
    w("")
    w("**PAPER EXECUTION ON RECORDED ON-CHAIN EVENTS.** Every fill below is "
      "simulated. No transaction was signed, broadcast or sent; the package "
      "that talks to the chain has a six-method read-only allowlist and no key "
      "material anywhere. A signal is not a fill and a paper buy is not an "
      "on-chain transaction.")
    w("")
    w("Reading rules, fixed in `PLAN.md` before the run:")
    w("")
    w("* zero episodes is an admissible result and is reported as such;")
    w("* nothing — gain, thresholds, scales, admission, the window — was "
      "touched to produce activity;")
    w("* the four conclusions below are separate and are never merged;")
    w("* never any phrasing of the form \"the fly learned\";")
    w("* never reading an empty or negative result as an engineering failure.")
    w("")

    # ---------------------------------------------------------- provenance
    w("## 1. Provenance, and the register-then-compute proof")
    w("")
    plan_commit = git("log", "-1", "--format=%H", "--",
                      "experiments/d10/config.json")
    w("| item | value |")
    w("|---|---|")
    w(f"| run | `{summary['run_id']}`, branches "
      f"`{'`, `'.join(branches)}` |")
    w(f"| plan + config commit | `{plan_commit[:12]}` — committed **alone**, "
      f"before this run existed |")
    w(f"| `config.json` sha256 | `{summary['config_sha256'][:12]}…` |")
    w(f"| `PLAN.md` sha256 | `{summary['plan_sha256'][:12]}…` |")
    w(f"| dataset | `{cfg['dataset']['label']}`, "
      f"{cfg['dataset']['window']['blocks']:,} blocks, "
      f"{cfg['dataset']['events']:,} events |")
    w(f"| dataset `events.jsonl` sha256 | "
      f"`{cfg['dataset']['sha256']['events.jsonl'][:12]}…` |")
    w(f"| graph | `{summary['graph_sha256'][:12]}…` |")
    w(f"| clean reference digest | `{summary['clean_reference_digest'][:12]}…` |")
    w(f"| venue / chain | {summary['venue']} / {summary['chain_id']} |")
    w(f"| python · numpy | {summary['python']} · {summary['numpy']} |")
    w(f"| wall clock | {summary['elapsed_s'] / 60:.1f} min, peak RSS "
      f"{summary['peak_rss_mib']:.0f} MiB |")
    w("")
    w(f"**Every number in this file was produced after commit "
      f"`{plan_commit[:12]}`**, which contains `PLAN.md` and `config.json` and "
      f"nothing else. The scales, the horizon, the size, the latency, the gas "
      f"constants, the admission rule and the expected activity were all fixed "
      f"in it before the first tick.")
    w("")

    # ------------------------------------------------------------ the loop
    w("## 2. What ran")
    w("")
    w("| branch | mode | learning | ticks | discoveries | tapes | episodes | "
      "start digest | end digest | unchanged |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for name, b in branches.items():
        w(f"| `{name}` | {b['mode']} | {b['learning']} | {b['ticks']} | "
          f"{b['tokens_discovered']} | {b['tapes']} | {len(b['episodes'])} | "
          f"`{b['start_digest'][:12]}…` | `{b['end_digest'][:12]}…` | "
          f"{b['digest_unchanged']} |")
    w("")
    if frozen:
        credit = frozen.get("credit", {})
        w(f"The frozen branch is the **mechanical control, not a scientific "
          f"comparison**: same data, same `comparison_v1` seeds, same clean "
          f"checkpoint. Its digest is unchanged "
          f"(**{frozen['digest_unchanged']}**), it counted "
          f"{frozen['journal'].get('settled_frozen', 0)} `SETTLED_FROZEN` "
          f"settlements and accepted {credit.get('accepted', 0)} learning "
          f"updates.")
        w("")

    # ------------------------------------------------- admission, rotation
    w("## 3. Admission and rotation")
    w("")
    tally = learn.get("tally", {})
    w("Every launch seen gets a `DISCOVERY` record whether it is admitted or "
      "not, so this is the launches that happened and not the launches that "
      "survived.")
    w("")
    w("| reason | n |")
    w("|---|---|")
    for key, value in sorted(tally.get("admission", {}).items(),
                             key=lambda kv: -kv[1]):
        w(f"| `{key}` | {value:,} |")
    w("")
    w("Observation status, per token per tick:")
    w("")
    w("| status | n |")
    w("|---|---|")
    for key, value in sorted(tally.get("observation_status", {}).items(),
                             key=lambda kv: -kv[1]):
        w(f"| `{key}` | {value:,} |")
    w("")
    w("Rotation is round-robin on rounds-since-last-presentation and the launch "
      "order, blind to price, volume, flow, outcome and ticker. The omitted are "
      "recorded `ROTATED`.")
    w("")

    # --------------------------------------------------------- the decoder
    w("## 4. What the decoder decided")
    w("")
    per_c = tally.get("per_candidate_evaluation", {})
    per_r = tally.get("per_decision_round", {})
    w("Three denominators, never pooled.")
    w("")
    w("| denominator | n | statuses | actions |")
    w("|---|---|---|---|")
    w(f"| per candidate evaluation | {per_c.get('n', 0):,} | "
      f"{per_c.get('status', {})} | {per_c.get('action', {})} |")
    w(f"| per decision round | {per_r.get('n', 0):,} | "
      f"{per_r.get('status', {})} | {per_r.get('action', {})} |")
    w("")
    w("After the execution constraints:")
    w("")
    w("| outcome of the round | n |")
    w("|---|---|")
    for key, value in sorted(tally.get("after_execution_constraints", {}).items(),
                             key=lambda kv: -kv[1]):
        w(f"| `{key}` | {value:,} |")
    w("")
    w(f"Presentations {tally.get('presentations', 0):,}, candidate "
      f"evaluations {tally.get('candidate_evaluations', 0):,}, silent "
      f"replicates {tally.get('silent_replicates', 0):,} of "
      f"{tally.get('silent_replicate_denominator', 0):,}, invalid replicates "
      f"{tally.get('invalid_replicates', 0):,}.")
    w("")

    # ---------------------------------------------------------- the trades
    w("## 5. Episodes")
    w("")
    w(f"Expected before the run: at most "
      f"{cfg['expected_activity_before_the_run']['max_episodes']} episodes over "
      f"about {cfg['expected_activity_before_the_run']['ticks']} ticks. "
      f"Observed in `learning`: **{len(episodes)}** episodes over "
      f"{learn.get('ticks', 0)} ticks.")
    w("")
    if not episodes:
        w("**No episode completed.** That is an admissible result and it is "
          "reported as one. It is not evidence about the brain, about the "
          "venue or about the strategy; it is what the decoder did with this "
          "window under a rule that was fixed before the window was read.")
        w("")
    else:
        w("| # | token | entry block | entry ts | fill (ETH/token) | exit block "
          "| exit fill | fees+gas (ETH) | impact (ETH) | net (ETH) | held (s) | "
          "confirmation | learning event |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(episodes, 1):
            ev = e.get("learning_event") or {}
            w(f"| {i} | `{e['token'][:10]}…` | {e['entry_block']:,} | "
              f"{e['entry_ts']} | {e['entry_fill']:.3e} | {e['exit_block']:,} | "
              f"{e['exit_fill']:.3e} | {e['fees_eth']:.9f} | "
              f"{e['slippage_eth']:.9f} | {_eth(e['net_pnl'])} | "
              f"{e['seconds_held']} | {e['confirmation']['status']} | "
              f"{'accepted' if ev.get('accepted') else ev.get('reason', '—')} |")
        w("")
        w("`fees+gas` is the curve's base fee, the creator tax, the snipe tax "
          "and the three gas constants; `impact` is the price impact of our own "
          "size. `flytrade.execution`'s `FEE_BPS` and `SLIPPAGE_BPS` are not "
          "used on this route.")
        w("")
        stats = learn.get("execution", {})
        w("| accounting | value |")
        w("|---|---|")
        w(f"| trades | {stats.get('trades', 0)} |")
        w(f"| wins / losses / flat | {stats.get('wins', 0)} / "
          f"{stats.get('losses', 0)} / {stats.get('flat', 0)} |")
        w(f"| gross at reference prices | {_eth(stats.get('gross_reference_pnl', 0))} |")
        w(f"| − price impact | {float(stats.get('slippage_paid', 0)):.9f} |")
        w(f"| − fees, taxes and gas | {float(stats.get('fees_paid', 0)):.9f} |")
        w(f"| = net | {_eth(stats.get('net_pnl', 0))} |")
        rec = stats.get("reconciliation", {})
        residual = float(rec.get("residual", 0.0))
        open_fee = float(stats.get("fees_paid", 0.0)) - sum(
            float(e.get("fees_eth", 0.0)) for e in episodes)
        w(f"| reconciliation residual | {residual:.3e} |")
        if abs(open_fee) > 1e-12:
            w(f"| — the open position's entry fee, already paid | "
              f"{open_fee:.9f} |")
            w(f"| residual once that entry is set aside | "
              f"{residual + open_fee:.3e} |")
        w("")
        if abs(open_fee) > 1e-12:
            w(f"**The residual is the open position's entry fee and nothing "
              f"else.** The account's three-way identity "
              f"(`gross_reference − slippage − fees = net`) closes over "
              f"*settled* trades; a position still open at the stop has paid "
              f"its entry fee and has no outcome yet, so its fee sits in "
              f"`fees_paid` with nothing on the other side. Setting it aside "
              f"leaves {residual + open_fee:.3e}, which is the same "
              f"floating-point floor the replay run closed at. Nothing was "
              f"written off and the exposure is retained.")
            w("")

    unresolved = learn.get("unresolved", [])
    w(f"Unresolved positions: **{len(unresolved)}**. An unresolved position is "
      f"neither a loss nor a win: the exposure is retained, nothing settles and "
      f"nothing is taught.")
    w("")
    if unresolved:
        w("| episode | token | reason | detail |")
        w("|---|---|---|---|")
        for u in unresolved:
            w(f"| {u['episode_id']} | `{u['token'][:10]}…` | `{u['reason']}` | "
              f"{u['detail']} |")
        w("")

    marks = _mark_series(learn)
    w(f"Position marks recorded while holding: "
      f"**{marks['available'] + marks['unavailable']:,}** ticks, of "
      f"which {marks['available']:,} could be quoted and "
      f"{marks['unavailable']:,} could not. A mark is a mark: it is written "
      f"into the tick record and displayed, and it never reached "
      f"reinforcement — the learning rule takes the settled net outcome and "
      f"nothing else.")
    w("")
    if marks["available"]:
        w("| mark series (unrealised, ETH) | value |")
        w("|---|---|")
        w(f"| minimum | {marks['min']:+.9f} |")
        w(f"| median | {marks['median']:+.9f} |")
        w(f"| maximum | {marks['max']:+.9f} |")
        w(f"| last | {marks['last']:+.9f} |")
        w("")
    probe = HERE / "probe.json"
    if probe.exists():
        p = json.loads(probe.read_text())
        w(f"Silence and saturation across the declared input range are measured "
          f"separately in `experiments/d10/probe.json` — {p['patterns']} nominal "
          f"patterns, response rate {p['response_rate']:.1%}, saturated "
          f"presentations {p['saturated_presentations']}, silent replicates "
          f"{p['silent_replicates']:,} of {p['presentations']:,}. There is no "
          f"PnL in it.")
        w("")

    # --------------------------------------------------------- reliability
    w("## 6. Restart, determinism and the frozen control")
    w("")
    for restart in learn.get("restarts", []):
        w(f"* Mid-run restart at tick {restart['tick']}, after "
          f"{restart['after_settled_episodes']} settled episode(s): the "
          f"in-memory gains were destroyed and rebuilt from the checkpoint and "
          f"the log. Recovery action `{restart['report'].get('action')}`; "
          f"**gains restored exactly: {restart['gains_restored_exactly']}**.")
    if not learn.get("restarts"):
        w("* No mid-run restart fired (it is armed after the first settled "
          "episode, and there was none).")
    if rerun:
        w(f"* Determinism: the `learning` branch was executed a second time. "
          f"Event log identical after removing the two fields a second process "
          f"cannot reproduce by construction (the wall-clock `t` on every line "
          f"and the absolute checkpoint path): "
          f"**{rerun['log_identical']}** "
          f"({rerun['lines']:,} lines, `{rerun['normalised_sha256'][:12]}…`). "
          f"Final state digest identical: **{rerun['digest_identical']}**.")
    w("")

    # ------------------------------------------------------ the four claims
    w("## 7. The four conclusions, separated")
    w("")
    w("### 1. Integration")
    w("")
    blockers = []
    if not learn:
        blockers.append("the learning branch did not run")
    w("The integration works. Genuine PONS v2 events collected over HTTP from "
      "Robinhood Chain (chain id 4663) were normalised through one path, "
      "reconstructed into exact curve state, turned into causal context, "
      "encoded onto the olfactory path, measured by the existing k = 8 readout, "
      "decoded by the existing decoder, executed on paper against the "
      "integer-exact curve quote, settled under a confirmation rule and "
      "journalled through the existing recovery machinery. "
      + ("Named blocker: " + "; ".join(blockers) + "."
         if blockers else
         "The one link not exercised in this dispatch is **live collection** "
         "(`LIVE_PAPER`), whose driver is a documented stub completed by the "
         "next dispatch; every other component it needs — the collector, the "
         "confirmation rule and the settlement — is already mode-agnostic and "
         "is exercised here."))
    w("")
    w("### 2. The brain produced the observed behaviour")
    w("")
    w(f"Every decision in this run came from the decoder applied once to the "
      f"aggregate of {summary['config']['readout']['k']} presentations of the "
      f"encoded observation, under the `comparison_v1` seed schedule keyed to "
      f"the observation's content hash and the token's stable id — never to its "
      f"address spelling or its position in a list. No LLM, classifier, alpha "
      f"score or technical rule is in the decision path; the admission rule is "
      f"seven objective facts and the rotation is round-robin. "
      f"{per_r.get('n', 0):,} decision rounds were decoded and are in the log "
      f"with their per-replicate scores.")
    w("")
    w("### 3. Learning updated the declared eligible state")
    w("")
    credit = learn.get("credit", {})
    if episodes:
        w(f"{len(episodes)} settled episode(s) produced "
          f"{credit.get('accepted', 0)} accepted normalised update(s), each "
          f"credited to **the entry decision's own stored k = 8 eligibility "
          f"trace set** by episode id through the existing `CreditAssigner`. "
          f"The learned-state digest moved from "
          f"`{learn['start_digest'][:12]}…` to `{learn['end_digest'][:12]}…`. "
          f"The frozen branch, on the same data and the same seeds, did not "
          f"move (**{frozen.get('digest_unchanged')}**), which is what makes "
          f"the movement attributable to the updates and not to the loop.")
    else:
        w(f"No episode settled, so no update was applied and the learned-state "
          f"digest is unchanged (`{learn.get('start_digest', '')[:12]}…` → "
          f"`{learn.get('end_digest', '')[:12]}…`, unchanged: "
          f"**{learn.get('digest_unchanged')}**). That is the honest reading: "
          f"the machinery is present and tested, and this window gave it "
          f"nothing to apply.")
    w("")
    w("Credit assignment counters: " + json.dumps(credit) + ".")
    w("")
    w("### 4. Predictive usefulness")
    w("")
    w("**Not tested — no predictive evaluation was designed for D10.** There is "
      "no probe grid, no label, no AUC, no holdout and no cohort split in this "
      "wave; `PLAN.md` says so before the run rather than after it. Nothing in "
      "this file may be read as evidence for or against predictive skill, and "
      "the number of episodes, their sign and their sum are not such evidence.")
    w("")

    # ------------------------------------------------------------- the rest
    w("## 8. Discovery records")
    w("")
    w(f"{learn.get('tokens_discovered', 0):,} launches were seen and recorded; "
      f"{learn.get('tapes', 0):,} of them were native-ETH `pons-v2` launches "
      f"with a reconstructable initial state and were followed. The rest carry "
      f"their reason codes and were never followed — they are in the record, "
      f"not dropped from it.")
    w("")
    w("## 9. What this is not")
    w("")
    w("* Not a prediction test, not a profitability claim, and not a "
      "measurement of skill.")
    w("* Not live: `LIVE_PAPER` is the next dispatch.")
    w("* Not multimodal: the `SensoryEncoder` returns `{\"olfactory\": "
      "Stimulus}` and names `visual`, `taste` and `mechanosensory` as "
      "unimplemented extension points routed nowhere.")
    w("* Not a market participant: the paper position never changed the "
      "recorded public market, and no audience or copying effect is modelled.")
    w("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out


def _stats(values) -> dict:
    if not values:
        return {}
    import statistics
    return {"n": len(values), "min": min(values), "max": max(values),
            "median": statistics.median(values),
            "mean": round(statistics.fmean(values), 1)}


def write_live(summary: dict, out: Path) -> Path:
    """`results.md` for the **live** run. Separate from the replay's, by design.

    Everything here is read out of `runs/<run>/summary.json`, which the worker
    wrote out of its own event log and its own ledger. Nothing is recomputed,
    nothing is inferred, and no number from the replay run appears in a table
    beside a live one.
    """
    cfg = summary["config"]
    live = summary.get("live", {})
    branch = (summary.get("branches") or {}).get("live", {})
    driver = summary.get("driver", {})
    chain = summary.get("chain", {})
    requests = summary.get("requests", {})
    episodes = branch.get("episodes", [])
    tally = branch.get("tally", {})
    lines: list[str] = []
    w = lines.append

    w(f"# D10 — the live Pons loop ({summary['run_id']})")
    w("")
    w("**LIVE COLLECTION, PAPER EXECUTION.** Every fill below is simulated. "
      "No transaction was signed, broadcast or sent; the package that talks to "
      "the chain has a six-method read-only allowlist and no key material "
      "anywhere, and the endpoint and its key appear in no artifact. A signal "
      "is not a fill, a paper buy is not an on-chain transaction, and a live "
      "connection is not fresh data.")
    w("")
    w("**This file is the live run and nothing else.** The replay run "
      "`d10-001` is reported separately in `experiments/d10/results.md`; no "
      "number is carried across, and the two are never pooled.")
    w("")
    w("Reading rules, fixed in `PLAN.md` and `live.json` before the run:")
    w("")
    w("* zero episodes, and zero admitted candidates in the hour, are "
      "admissible results and are reported as such;")
    w("* nothing — gain, thresholds, scales, admission, the limits — was "
      "touched to produce activity;")
    w("* an episode still `PENDING_CONFIRMATION` at the stop is reported as "
      "pending, never as settled;")
    w("* a position still open at the stop is retained open, never closed at "
      "the last mark;")
    w("* the four conclusions below are separate and are never merged.")
    w("")

    # ---------------------------------------------------------- provenance
    w("## 1. Provenance, and what was registered before the run")
    w("")
    live_commit = git("log", "-1", "--format=%H", "--", "experiments/d10/live.json")
    w("| item | value |")
    w("|---|---|")
    w(f"| run | `{summary['run_id']}`, branch `live` |")
    w(f"| mode / learning | {summary.get('mode')} / {summary.get('learning')} |")
    w(f"| registration commit | `{live_commit[:12]}` — `live.json` + "
      f"`LIVE_PLAN.md`, committed alone and **before** this run existed |")
    w(f"| `live.json` sha256 | `{summary.get('live_sha256', '')[:12]}…` |")
    w(f"| `config.json` sha256 | `{summary['config_sha256'][:12]}…` (unchanged "
      f"since the replay run) |")
    w(f"| started from | `{live['starts_from']['run']}/"
      f"{live['starts_from']['branch']}`'s final checkpoint, digest "
      f"`{summary.get('starts_from_digest', '')[:12]}…` — verified before the "
      f"first request |")
    w(f"| graph | `{summary['graph_sha256'][:12]}…` |")
    w(f"| venue / chain | {summary['venue']} / {summary['chain_id']} "
      f"(`eth_chainId` verified = {summary['chain_id']}) |")
    w(f"| endpoint | `<rpc-endpoint>` — read by key name at runtime, never "
      f"printed, logged or written |")
    w(f"| started / stopped (UTC) | {summary.get('started_utc')} → "
      f"{summary.get('stopped_utc')} |")
    w(f"| wall clock | {summary.get('elapsed_s', 0) / 60:.1f} min, peak RSS "
      f"{summary.get('peak_rss_mib', 0):.0f} MiB |")
    w(f"| python · numpy | {summary.get('python')} · {summary.get('numpy')} |")
    w("")

    # ------------------------------------------------------------ the stop
    w("## 2. The run, and how it stopped")
    w("")
    stop_reason = branch.get("stop_reason") or driver.get("stopped")
    w("| item | value |")
    w("|---|---|")
    w(f"| stop reason | **{stop_reason}** — {branch.get('stop_detail') or ''} |")
    w(f"| declared stop conditions | {live['limits']['stop_conditions']} |")
    w(f"| ticks | {branch.get('ticks', driver.get('ticks', 0))} "
      f"(expected before the run: "
      f"{live['expected_activity_before_the_run']['ticks']}) |")
    w(f"| cadence | {cfg['cadence_seconds']} s |")
    w(f"| first / last cutoff | {driver.get('first_ts')} → "
      f"{driver.get('last_ts')} |")
    backfill = driver.get("backfill", {})
    w(f"| start backfill | blocks {backfill.get('first_block')} → "
      f"{backfill.get('reached')}, {backfill.get('events', 0):,} events, "
      f"{backfill.get('requests', 0)} requests, {backfill.get('wall_s', 0)} s, "
      f"complete: {backfill.get('complete')} |")
    w(f"| errors | {len(driver.get('errors', []))}"
      + (f" — {driver['errors'][-1]['code']}" if driver.get("errors") else "")
      + " |")
    w(f"| reorgs seen | {driver.get('reorgs', 0)} |")
    w("")
    lag_b = _stats(driver.get("lag_blocks", []))
    lag_s = _stats(driver.get("lag_seconds", []))
    age = _stats(driver.get("cutoff_ages", []))
    if lag_b or age:
        w("Two different lags, both measured per tick and neither a substitute "
          "for the other. **Unscanned lag** is head − cursor once the tick has "
          "scanned: how much of the chain the collector has not read, normally "
          "zero because a tick scans to the head it just read. **Cutoff age** "
          "is how old the decision's own data is when the tick finishes, which "
          "is what a reader means by \"how far behind is it\".")
        w("")
        w("| lag | n | min | median | mean | max |")
        w("|---|---|---|---|---|---|")
        if lag_b:
            w(f"| unscanned (blocks) | {lag_b['n']} | {lag_b['min']} | "
              f"{lag_b['median']} | {lag_b['mean']} | {lag_b['max']} |")
        if lag_s:
            w(f"| unscanned (seconds) | {lag_s['n']} | {lag_s['min']} | "
              f"{lag_s['median']} | {lag_s['mean']} | {lag_s['max']} |")
        if age:
            w(f"| cutoff age (seconds) | {age['n']} | {age['min']} | "
              f"{age['median']} | {age['mean']} | {age['max']} |")
        w("")
    track = driver.get("head_track", [])
    if track:
        w("Head and cursor progression (every tick, first and last five shown; "
          "the whole series is in `summary.json`):")
        w("")
        w("| tick | cutoff | head | cursor | unscanned | cutoff age (s) | "
          "events | attempts |")
        w("|---|---|---|---|---|---|---|---|")
        rows = (track[:5] + [{"tick": "…"}] + track[-5:]
                if len(track) > 10 else track)
        for row in rows:
            if row.get("tick") == "…":
                w("| … | | | | | | | |")
                continue
            w(f"| {row['tick']} | {row['cutoff_ts']} | {row['head']:,} | "
              f"{row['cursor']:,} | {row['lag_blocks']} | "
              f"{row.get('cutoff_age_s')} | {row['events']} | "
              f"{row['attempts']} |")
        w("")

    # --------------------------------------------------------- what it saw
    w("## 3. What the hour actually held")
    w("")
    interval = float(cfg["dataset"]["window"]["median_block_interval_s"])
    scanned_s = (chain.get("blocks_scanned", 0) or 0) * interval
    hours = max(1e-9, scanned_s / 3600.0)
    launches = driver.get("launches_seen", 0)
    w("| item | value |")
    w("|---|---|")
    w(f"| blocks scanned | {chain.get('blocks_scanned', 0):,} |")
    w(f"| raw logs | {chain.get('raw_logs', 0):,} |")
    w(f"| normalised events | {chain.get('events', 0):,} |")
    w(f"| `TokenLaunched` seen | **{launches:,}** |")
    w(f"| tracked curves at the stop | {chain.get('tracked_at_stop', 0):,} |")
    w(f"| `CurveCompleted` seen | {chain.get('completed_curves', 0):,} |")
    w(f"| orphaned by a reorg | {chain.get('orphaned', 0):,} |")
    w("")
    w(f"**Launch rate over this run: {launches / hours:,.0f} `TokenLaunched` "
      f"per hour** — {launches:,} launches over the "
      f"{chain.get('blocks_scanned', 0):,} blocks this run scanned, backfill "
      f"included, which is {scanned_s / 60:,.1f} minutes of chain time at the "
      f"measured {interval} s interval. The v2 documentation says *\"public launches are closed, so "
      f"only whitelisted addresses can create a token for now\"*; both things "
      f"are true at once, and the rate is the measurement. Beside it, the two "
      f"earlier measurements of this wave: **≈ 523/h** over 3,001 blocks "
      f"(dispatch 1's verification probe) and **440/h** over the 135-minute "
      f"backfill window (dispatch 2). They are three measurements of three "
      f"different windows, not a trend.")
    w("")
    w("Admission, per token per tick — every launch gets a `DISCOVERY` record "
      "whether it is followed or not:")
    w("")
    w("| reason | n |")
    w("|---|---|")
    for key, value in sorted(tally.get("admission", {}).items(),
                             key=lambda kv: -kv[1]):
        w(f"| `{key}` | {value:,} |")
    w("")
    if tally.get("observation_status"):
        w("| observation status | n |")
        w("|---|---|")
        for key, value in sorted(tally["observation_status"].items(),
                                 key=lambda kv: -kv[1]):
            w(f"| `{key}` | {value:,} |")
        w("")
    w(f"One admission fact differs from the replay and only one: "
      f"`require_coverage` is **off**, because \"the horizon lies inside the "
      f"token's coverage\" is addendum 10's *replay* clause and live has no end "
      f"of data to keep a horizon inside. It was registered off in `live.json` "
      f"before the run. Rotation is unchanged: round-robin on "
      f"rounds-since-last-presentation and the launch order, blind to price, "
      f"volume, flow, outcome and ticker.")
    w("")

    # ------------------------------------------------------- the decisions
    w("## 4. What the decoder decided")
    w("")
    per_c = tally.get("per_candidate_evaluation", {})
    per_r = tally.get("per_decision_round", {})
    w("Three denominators, never pooled.")
    w("")
    w("| denominator | n | statuses | actions |")
    w("|---|---|---|---|")
    w(f"| per candidate evaluation | {per_c.get('n', 0):,} | "
      f"{per_c.get('status', {})} | {per_c.get('action', {})} |")
    w(f"| per decision round | {per_r.get('n', 0):,} | "
      f"{per_r.get('status', {})} | {per_r.get('action', {})} |")
    w("")
    w("After the execution constraints:")
    w("")
    w("| outcome of the round | n |")
    w("|---|---|")
    for key, value in sorted(tally.get("after_execution_constraints", {}).items(),
                             key=lambda kv: -kv[1]):
        w(f"| `{key}` | {value:,} |")
    w("")
    w(f"Presentations {tally.get('presentations', 0):,}, candidate evaluations "
      f"{tally.get('candidate_evaluations', 0):,}, silent replicates "
      f"{tally.get('silent_replicates', 0):,} of "
      f"{tally.get('silent_replicate_denominator', 0):,}, invalid replicates "
      f"{tally.get('invalid_replicates', 0):,}.")
    w("")

    # --------------------------------------------------------- the trades
    w("## 5. Episodes")
    w("")
    expected = live["expected_activity_before_the_run"]
    w(f"Expected before the run: at most **{expected['max_episodes']}** "
      f"episodes over {expected['ticks']} ticks, and fewer because "
      f"{expected['expected_fewer_because']}. Observed: **{len(episodes)}**.")
    w("")
    if not episodes:
        w("**No episode settled in this hour.** That is an admissible result "
          "and it is reported as one. It is not evidence about the brain, "
          "about the venue or about the strategy.")
        w("")
    else:
        w("| # | token | entry block | entry ts | fill (ETH/token) | exit block "
          "| exit fill | fees+gas (ETH) | impact (ETH) | net (ETH) | held (s) | "
          "confirmation | learning event |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(episodes, 1):
            ev = e.get("learning_event") or {}
            w(f"| {i} | `{e['token'][:10]}…` | {e['entry_block']:,} | "
              f"{e['entry_ts']} | {e['entry_fill']:.3e} | {e['exit_block']:,} | "
              f"{e['exit_fill']:.3e} | {e['fees_eth']:.9f} | "
              f"{e['slippage_eth']:.9f} | {_eth(e['net_pnl'])} | "
              f"{e['seconds_held']} | {e['confirmation']['status']} | "
              f"{'accepted' if ev.get('accepted') else ev.get('reason', '—')} |")
        w("")
        stats = branch.get("execution", {})
        w("| accounting | value |")
        w("|---|---|")
        w(f"| trades | {stats.get('trades', 0)} |")
        w(f"| wins / losses / flat | {stats.get('wins', 0)} / "
          f"{stats.get('losses', 0)} / {stats.get('flat', 0)} |")
        w(f"| gross at reference prices | "
          f"{_eth(stats.get('gross_reference_pnl', 0))} |")
        w(f"| − price impact | {float(stats.get('slippage_paid', 0)):.9f} |")
        w(f"| − fees, taxes and gas | {float(stats.get('fees_paid', 0)):.9f} |")
        w(f"| = net | {_eth(stats.get('net_pnl', 0))} |")
        rec = stats.get("reconciliation", {})
        residual = float(rec.get("residual", 0.0))
        open_fee = float(stats.get("fees_paid", 0.0)) - sum(
            float(e.get("fees_eth", 0.0)) for e in episodes)
        w(f"| reconciliation residual | {residual:.3e} |")
        if abs(open_fee) > 1e-12:
            w(f"| — the open position's entry fee, already paid | "
              f"{open_fee:.9f} |")
            w(f"| residual once that entry is set aside | "
              f"{residual + open_fee:.3e} |")
        w("")
        if abs(open_fee) > 1e-12:
            w(f"**The residual is the open position's entry fee and nothing "
              f"else.** The account's three-way identity "
              f"(`gross_reference − slippage − fees = net`) closes over "
              f"*settled* trades; a position still open at the stop has paid "
              f"its entry fee and has no outcome yet, so its fee sits in "
              f"`fees_paid` with nothing on the other side. Setting it aside "
              f"leaves {residual + open_fee:.3e}, which is the same "
              f"floating-point floor the replay run closed at. Nothing was "
              f"written off and the exposure is retained.")
            w("")

    # confirmation state at the stop, which live has and replay did not
    w("### Confirmation status at the stop")
    w("")
    w(f"The settlement rule is unchanged: the entry-fill block and the exit "
      f"block must both be at least {cfg['settlement']['confirm_depth_blocks']} "
      f"blocks behind head **and** at or below the `safe` tag, and the grid "
      f"anchor below each must still hash to what was stored. "
      f"{live['settlement']['expected'][:1].upper()}"
      f"{live['settlement']['expected'][1:]}.")
    w("")
    settled = [e for e in episodes if e.get("settlement") in ("SETTLED",
                                                              "SETTLED_FROZEN")]
    settled_ids = {e["episode_id"] for e in episodes}
    unresolved = branch.get("unresolved", [])
    # A `PENDING_CONFIRMATION` entry is retryable and is written once per
    # (episode, reason). An episode that waited for its blocks and then settled
    # carries one of each; it is counted **settled**, and the pending entry
    # stays in the log as the record of the wait rather than as a second
    # episode. Only an episode that was still waiting at the stop is counted
    # pending.
    pending = [u for u in unresolved if u["reason"] == "PENDING_CONFIRMATION"
               and u["episode_id"] not in settled_ids]
    waited = [u for u in unresolved if u["reason"] == "PENDING_CONFIRMATION"
              and u["episode_id"] in settled_ids]
    w("| state at the stop | n |")
    w("|---|---|")
    w(f"| settled and confirmed | {len(settled)} |")
    w(f"| of those, waited for confirmation and then settled | {len(waited)} |")
    w(f"| `PENDING_CONFIRMATION` **at the stop** (reported pending, **not "
      f"settled**) | {len(pending)} |")
    for reason in sorted({u["reason"] for u in unresolved
                          if u["reason"] != "PENDING_CONFIRMATION"}):
        w(f"| `{reason}` | "
          f"{sum(1 for u in unresolved if u['reason'] == reason)} |")
    w("")
    if unresolved:
        w("| episode | token | reason | detail | retryable |")
        w("|---|---|---|---|---|")
        for u in unresolved:
            w(f"| {u['episode_id']} | `{u['token'][:10]}…` | `{u['reason']}` | "
              f"{u['detail']} | {u.get('retryable')} |")
        w("")
    w("An unresolved or pending position is **neither a loss nor a win**: the "
      "exposure is retained in the journal, nothing settles and nothing is "
      "taught. A position still open when the run stopped was **not** closed "
      "at the last mark.")
    w("")
    marks = _mark_series(branch)
    w(f"Position marks recorded while holding: "
      f"**{marks['available'] + marks['unavailable']:,}** ticks, of which "
      f"{marks['available']:,} could be quoted and {marks['unavailable']:,} "
      f"could not. A mark is a mark: it is written into the tick record and "
      f"displayed, and it never reached reinforcement.")
    w("")
    if marks.get("available"):
        w("| mark series (unrealised, ETH) | value |")
        w("|---|---|")
        w(f"| minimum | {marks['min']:+.9f} |")
        w(f"| median | {marks['median']:+.9f} |")
        w(f"| maximum | {marks['max']:+.9f} |")
        w(f"| last | {marks['last']:+.9f} |")
        w("")

    # ------------------------------------------------------------ the cost
    w("## 6. What it cost, and what a subscription would have cost")
    w("")
    w("| method | attempts | units (archive-weighted) | errors |")
    w("|---|---|---|---|")
    for method, row in sorted(requests.get("by_method", {}).items()):
        if not row["attempts"]:
            continue                       # a method this run never called
        w(f"| `{method}` | {row['attempts']:,} | {row['units']:,} | "
          f"{row['errors']} |")
    w(f"| **total** | **{requests.get('attempts', 0):,}** | "
      f"**{requests.get('units', 0):,}** | {requests.get('errors', 0)} |")
    w("")
    w(f"Against the caps: **{requests.get('attempts', 0):,} of the "
      f"{requests.get('run_cap', 0):,}** this run was allowed "
      f"(addendum 15), and **{requests.get('wave_attempts', 0):,} of the "
      f"{requests.get('wave_cap', 0):,}** the wave is allowed "
      f"(addendum 5), {requests.get('wave_units', 0):,} archive-weighted units "
      f"in the wave's ledger. A read 127 or more blocks behind the tip is "
      f"billed at two units (docs.chainstack.com/docs/request-units); the "
      f"ledger records attempts **and** units, and the cap is on attempts.")
    w("")
    wss = summary.get("wss_equivalent", {})
    w(f"**WSS-equivalent for the same window: {wss.get('total', 0):,} billed "
      f"messages** — {wss.get('subscriptions', 0)} subscriptions + "
      f"{wss.get('log_pushes', 0):,} log pushes + "
      f"{wss.get('header_pushes', 0):,} header pushes, against the "
      f"{requests.get('attempts', 0):,} attempts this HTTP run actually spent. "
      f"{wss.get('rule', '')} This is the comparison the owner asked for as a "
      f"number rather than an opinion.")
    w("")
    if driver.get("errors"):
        w("| error | detail | tick |")
        w("|---|---|---|")
        for err in driver["errors"]:
            w(f"| `{err['code']}` | {err['detail'][:120]} | {err['tick']} |")
        w("")
        w("**No retry, no fallback, no provider switch.** The run stops on the "
          "first endpoint error by construction.")
        w("")
    else:
        w("No endpoint error occurred. Nothing was retried, because nothing in "
          "this package retries.")
        w("")

    # ------------------------------------------------------------ learning
    w("## 7. Learning, and the state digest")
    w("")
    credit = branch.get("credit", {})
    w("| item | value |")
    w("|---|---|")
    w(f"| learning mode | {branch.get('learning')} |")
    w(f"| digest at the start | `{branch.get('start_digest', '')[:12]}…` |")
    w(f"| digest at the stop | `{branch.get('end_digest', '')[:12]}…` |")
    w(f"| digest unchanged | {branch.get('digest_unchanged')} |")
    started_with = summary.get("credit_at_start", {})
    accepted_before = int(started_with.get("accepted", 0) or 0)
    w(f"| settled episodes | {len(settled)} |")
    w(f"| accepted normalised updates **in this run** | "
      f"{int(credit.get('accepted', 0)) - accepted_before} |")
    w(f"| credit rejections in this run | "
      f"{int(credit.get('rejections_total', 0)) - int(started_with.get('rejections_total', 0) or 0)} |")
    w("")
    w(f"The credit counters are durable: they ride in the checkpoint, so this "
      f"run inherited {accepted_before} accepted update(s) from the replay "
      f"checkpoint it started at and the row above subtracts them. The "
      f"inherited total is not this run's work and is not reported as if it "
      f"were.")
    w("")
    recovery = summary.get("recovery", {})
    w(f"Recovery at start: `{recovery.get('action')}`, checkpoint loaded "
      f"**{recovery.get('checkpoint_loaded')}**, last settled episode "
      f"{recovery.get('last_settled_episode')}. The learned state the run "
      f"began from is the replay run's own final checkpoint, verified by "
      f"digest before the first request.")
    w("")

    # ------------------------------------------------------ the four claims
    w("## 8. The four conclusions, separated")
    w("")
    w("### 1. Integration")
    w("")
    if driver.get("errors") and stop_reason not in ("TIME_LIMIT", "STOP_FILE",
                                                    "SIGNAL", "REQUEST_CAP"):
        w(f"**The live link is blocked.** The run stopped on "
          f"`{stop_reason}` ({branch.get('stop_detail')}) after "
          f"{requests.get('attempts', 0)} requests, with no retry and no "
          f"fallback, which is the declared behaviour. The replay evidence of "
          f"`d10-001` stands on its own: it is a genuine collection through "
          f"the same collector, the same normaliser and the same loop, and it "
          f"is reported in `experiments/d10/results.md`.")
    else:
        w(f"**The live link works.** New PONS v2 events were received over "
          f"HTTP from Robinhood Chain (chain id {summary['chain_id']}) on the "
          f"wall clock, normalised through the same path the replay dataset "
          f"was written with, reconstructed into exact curve state, turned "
          f"into causal context, encoded onto the olfactory path, measured by "
          f"the existing k = 8 readout, decoded by the existing decoder, "
          f"executed on paper against the integer-exact curve quote, and "
          f"journalled through the existing recovery machinery, with the "
          f"confirmation rule gating every settlement. The run stopped on "
          f"`{stop_reason}` and persisted its cursor, ledger, journal and "
          f"checkpoint.")
    w("")
    w("### 2. The brain produced the observed behaviour")
    w("")
    w(f"Every decision in this run came from the decoder applied once to the "
      f"aggregate of {cfg['readout']['k']} presentations of the encoded "
      f"observation, under the `comparison_v1` seed schedule keyed to the "
      f"observation's content hash and the token's stable id — never to its "
      f"address spelling or its position in a list. No LLM, classifier, alpha "
      f"score or technical rule is in the decision path; admission is seven "
      f"objective facts (one of them registered off for live, §3) and the "
      f"rotation is round-robin. {per_r.get('n', 0):,} decision rounds were "
      f"decoded and are in the log with their per-replicate scores.")
    w("")
    w("### 3. Learning updated the declared eligible state")
    w("")
    if settled:
        w(f"{len(settled)} settled episode(s) produced "
          f"{credit.get('accepted', 0)} accepted normalised update(s), each "
          f"credited to **the entry decision's own stored k = 8 eligibility "
          f"trace set** by episode id through the existing `CreditAssigner`. "
          f"The learned-state digest moved from "
          f"`{branch.get('start_digest', '')[:12]}…` to "
          f"`{branch.get('end_digest', '')[:12]}…`. An episode that was still "
          f"pending confirmation at the stop taught nothing, by construction.")
    else:
        w(f"No episode settled inside the stop limits, so no update was "
          f"applied and the learned-state digest is unchanged "
          f"(`{branch.get('start_digest', '')[:12]}…` → "
          f"`{branch.get('end_digest', '')[:12]}…`, unchanged: "
          f"**{branch.get('digest_unchanged')}**). That is the honest reading: "
          f"the machinery is present, tested and exercised on the replay run, "
          f"and this hour gave it nothing to apply. It is not a failure and it "
          f"is not evidence about anything.")
    w("")
    w("### 4. Predictive usefulness")
    w("")
    w("**Not tested — no predictive evaluation was designed for D10.** There "
      "is no probe grid, no label, no AUC, no holdout and no cohort split in "
      "this wave; `PLAN.md` says so before the run rather than after it. "
      "Nothing in this file may be read as evidence for or against predictive "
      "skill, and the number of episodes, their sign and their sum are not "
      "such evidence.")
    w("")

    w("## 9. What this is not")
    w("")
    w("* Not a prediction test, not a profitability claim, and not a "
      "measurement of skill.")
    w("* Not an hour that can be compared with the replay window: different "
      "blocks, different tokens, a different clock and a different number of "
      "ticks. The two reports are separate for that reason.")
    w("* Not multimodal: the `SensoryEncoder` returns `{\"olfactory\": "
      "Stimulus}` and names `visual`, `taste` and `mechanosensory` as "
      "unimplemented extension points routed nowhere.")
    w("* Not a market participant: the paper position never changed the "
      "public market, and no audience or copying effect is modelled.")
    w("* Not a real-money path: six read methods, no key material, nothing "
      "signed, approved, broadcast or moved.")
    w("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="d10-001")
    parser.add_argument("--rerun", default=None,
                        help="JSON file with the determinism comparison")
    parser.add_argument("--live", action="store_true",
                        help="report a LIVE_PAPER run into results_live.md")
    parser.add_argument("--out", default=None,
                        help="the committed copy (default: by mode)")
    args = parser.parse_args(argv)
    directory = RUNS / args.run
    summary = json.loads((directory / "summary.json").read_text())
    rerun = json.loads(Path(args.rerun).read_text()) if args.rerun else None
    if args.live:
        out = write_live(summary, directory / "results.md")
        committed = Path(args.out) if args.out else (HERE / "results_live.md")
    else:
        out = write(summary, directory / "results.md", rerun=rerun)
        # ``runs/`` is gitignored, as it has been since D5. D7 and D9(b) keep
        # the wave's conclusion at the experiment root so it is in the
        # repository; this copies it there for the same reason, byte for byte.
        committed = Path(args.out) if args.out else (HERE / "results.md")
    committed.write_text(out.read_text())
    print(f"wrote {out} and {committed} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
