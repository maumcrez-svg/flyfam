"""
Synthetic event logs for the viewer's tests. Amendment D9(a) §9, addendum 12.

**Every event written here carries ``"dataset_label": "SYNTHETIC_FIXTURE"``.**
That is the whole point of the file: the viewer's mode strip reads that field,
so nothing built here can appear on the screen as a historical experiment
result, and a test that accidentally pointed the page at a fixture would show
SYNTHETIC FIXTURE in the strip rather than HISTORICAL REPLAY.

The shapes are copied from what the run actually writes (``flytrade/records.py``
``record_round`` / ``record_decision`` / ``open_episode`` / ``settle`` /
``settle_frozen``) — the field names are verified against the real
``d7-001/learned`` log — but no number here came from a market. They exist to
exercise the states amendment §4 lists, including the ones the selected
historical run never reached: ``INVALID_STATE``, ``POLICY_CLOSE``, a refused
learning update, and a decision whose optional telemetry is missing.

Nothing in this module imports :mod:`flytrade`.
"""
from __future__ import annotations

import json

LABEL = "SYNTHETIC_FIXTURE"
T0 = 1_780_000_000            # an arbitrary epoch second; not a market date
GLOM = ("DA2", "DL1", "DM2", "DM3", "DM6", "V", "VL1", "VL2a", "VM4", "VM5d")


class Log:
    """An append-only list of events, in the order the journal writes them."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def append(self, kind: str, body: dict) -> dict:
        e = {"kind": kind, "t": 1_789_000_000.0 + len(self.events),
             "dataset_label": LABEL, **body}
        self.events.append(e)
        return e

    def write(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            for e in self.events:
                fh.write(json.dumps(e, sort_keys=True) + "\n")
        return path


def partition(log: Log, name: str, boundary: str, *, branch: str,
              learning: bool | None = None) -> None:
    body = {"partition": name, "boundary": boundary, "branch": branch,
            "run_id": "synthetic-001", "state_digest": "s" * 64}
    if boundary == "start":
        body["learning"] = learning
        body["neural"] = True
    log.append("PARTITION", body)


def round_(log: Log, *, i: int, ts: int, status: str = "OK",
           episode_id: int = 0, silent: int = 0) -> None:
    log.append("ROUND", {
        "round_index": i, "cutoff_ts": ts, "round_seed": 1,
        "selection_rule": "highest |score|",
        "candidates": [{"symbol": "SYN", "stable_id": 0, "k": 8,
                        "status": status, "episode_id": episode_id,
                        "seed": 7, "eligible": 10, "eligible_union": 10,
                        "silent_replicates": silent}],
        "selected_stable_id": 0 if status == "OK" else None})


def decision(log: Log, *, episode_id: int, ts: int, action: str,
             status: str, valence: float, branch: str, partition_name: str,
             telemetry: bool = True, kc_fraction: float = 0.05,
             max_rate_hz: float = 100.0, reps: list[str] | None = None,
             ) -> dict:
    """One DECISION, in the shape ``record_decision`` writes.

    ``telemetry=False`` drops ``observation`` / ``stimulus`` / ``readout`` /
    the replicate arrays — the optional-telemetry case §4 asks the viewer to
    show as "unavailable" rather than as zero.
    """
    body = {
        "episode_id": episode_id, "symbol": "SYN", "stable_id": 0,
        "bar_index": episode_id // 1000, "cutoff_ts": ts, "market_ts": ts,
        "seed": 11, "decoded_action": action, "readout_status": status,
        "checkpoint_digest": "c" * 64, "decision_digest": "d" * 64,
        "k": 8, "brain_cycle": episode_id // 1000, "brain_ms": 500.0,
        "partition": partition_name, "branch": branch,
        "run_id": "synthetic-001", "observation_status": "OK",
        "valence_hz": valence, "approach_hz": 6.0, "avoid_hz": 6.5,
        "theta_hz": 0.9, "n_candidates": 1,
        "versions": {"encoder": "synthetic", "decoder": "synthetic"},
    }
    if telemetry:
        body["observation"] = {
            "close": 100.0 + episode_id / 1000.0, "bar_index": 1,
            "normalized": {"r1": 0.1, "r5": -0.2, "r20": 0.3, "rv20": 0.4,
                           "relvol": -0.5},
            "raw": {"r1": 0.001, "r5": -0.002, "r20": 0.003, "rv20": 0.004,
                    "relvol": -0.5}}
        body["stimulus"] = {"rates_hz": {g: 10.0 + i for i, g in
                                         enumerate(GLOM)},
                            "n_orns": 700, "total_drive_hz": 12000.0}
        body["readout"] = {"rates_hz": {"approach": 6.0, "avoid": 6.5},
                           "population_sizes": {"approach": 16, "avoid": 29},
                           "kc_fraction": kc_fraction, "kc_active": 130,
                           "max_rate_hz": max_rate_hz,
                           "silent_replicates": 1, "k": 8}
        body["replicate_scores"] = [1.0, -2.0, 0.5, -1.5, 0.25, -0.5, 2.0, 3.0]
        body["replicate_statuses"] = reps or (
            ["VALID"] * 7 + ["NO_RESPONSE"])
    return log.append("DECISION", body)


def execution(log: Log, *, episode_id: int, ts: int, price: float = 100.0,
              flag: str = "", delay: int = 1) -> None:
    log.append("EXECUTION", {
        "episode_id": episode_id, "symbol": "SYN", "k": 8, "side": "BUY",
        "bar_index": 1, "ts": ts, "market_ts": ts, "fill_price": price,
        "reference_price": price - 0.05, "quantity": 10.0, "fee": 0.5,
        "slippage": 0.5, "value": 1000.0, "flag": flag,
        "delay_minutes": delay})


def outcome(log: Log, *, episode_id: int, ts: int, net: float,
            close_reason: str = "NEURAL_SELL", held: int = 3,
            frozen: bool = False, cash: float = 10_000.0,
            trades: int = 1, account: bool = True) -> None:
    body = {
        "episode_id": episode_id, "symbol": "SYN", "stable_id": 0,
        "ts": ts, "market_ts": ts, "close_reason": close_reason,
        "market_minutes_held": held, "bars_held": held,
        "gross_reference_pnl": net + 1.0, "gross_pnl": net + 1.0,
        "slippage": 1.0, "fees": 1.0, "net_pnl": net, "notional": 1000.0,
        "return_on_notional": net / 1000.0,
        "cumulative_realized_pnl": net, "entry_flag": "", "exit_flag": "",
        "execution_version": "synthetic",
        "entry": {"fill_price": 100.0, "side": "BUY"},
        "exit": {"fill_price": 100.0 + net / 10.0, "side": "SELL"}}
    if frozen:
        body["settlement"] = "SETTLED_FROZEN"
    if account:
        body["account"] = {"cash": cash + net, "equity": cash + net,
                           "initial_cash": cash, "realized_pnl": net,
                           "fees_paid": 1.0, "slippage_paid": 1.0,
                           "position": None, "trades": trades}
    log.append("OUTCOME", body)


def learning(log: Log, *, episode_id: int, valence: int, amount: float,
             accepted: bool = True, reason: str = "",
             synapses: int = 1200) -> None:
    log.append("LEARNING", {
        "episode_id": episode_id, "accepted": accepted, "valence": valence,
        "amount": amount, "reason": reason, "k": 8,
        "normalisation": "mean_of_deltas",
        "eligibility_source": "replayed_from_decision",
        "synapses_depressed": synapses if accepted else 0,
        "trace_eligible": 5000 if accepted else 0,
        "depressed_per_replicate": [synapses // 8] * 8 if accepted else None})


# ------------------------------------------------------------------ the logs

def learning_branch() -> Log:
    """A LEARNING partition holding every §4 distinction the screen names.

    In order: a round with no decision; a decoded WAIT; a NO_RESPONSE; an
    INVALID_STATE (saturated readout); a SELL signal with no position open —
    which is a signal and **not** an executed sale; a BUY that the execution
    policy refused; a BUY that filled, was closed by a neural SELL at a loss
    and was punished; a second BUY closed by the policy horizon at a profit
    and rewarded; and a third whose learning update was refused because no
    synapse was eligible.
    """
    log = Log()
    log.append("CHECKPOINT", {"episode_id": -1, "digest": "a" * 64})
    partition(log, "LEARNING", "start", branch="learned", learning=True)
    t = T0

    round_(log, i=0, ts=t, status="WARMUP")           # no decision follows
    t += 60
    round_(log, i=1, ts=t)
    decision(log, episode_id=1000, ts=t, action="WAIT", status="VALID",
             valence=0.1, branch="learned", partition_name="LEARNING")
    t += 60
    round_(log, i=2, ts=t)
    decision(log, episode_id=2000, ts=t, action="NO_RESPONSE",
             status="NO_RESPONSE", valence=0.844, branch="learned",
             partition_name="LEARNING",
             reps=["NO_RESPONSE"] * 8)
    t += 60
    round_(log, i=3, ts=t)
    decision(log, episode_id=3000, ts=t, action="NO_RESPONSE",
             status="INVALID_STATE", valence=0.0, branch="learned",
             partition_name="LEARNING", kc_fraction=0.31, max_rate_hz=440.0)
    t += 60
    round_(log, i=4, ts=t)
    decision(log, episode_id=4000, ts=t, action="SELL", status="VALID",
             valence=-2.0, branch="learned", partition_name="LEARNING")
    t += 60
    round_(log, i=5, ts=t)
    decision(log, episode_id=5000, ts=t, action="BUY",
             status="POLICY_REJECT", valence=2.0, branch="learned",
             partition_name="LEARNING")

    # ---- a losing episode: BUY, fill, neural SELL, punishment
    t += 60
    round_(log, i=6, ts=t)
    decision(log, episode_id=6000, ts=t, action="BUY", status="VALID",
             valence=2.5, branch="learned", partition_name="LEARNING")
    t += 60
    execution(log, episode_id=6000, ts=t)
    t += 180
    outcome(log, episode_id=6000, ts=t, net=-4.5, held=3)
    log.append("CHECKPOINT", {"episode_id": 6000, "digest": "b" * 64})
    learning(log, episode_id=6000, valence=-1, amount=0.0045)

    # ---- a winning episode closed by the policy horizon, not by the fly
    t += 60
    round_(log, i=7, ts=t)
    decision(log, episode_id=7000, ts=t, action="BUY", status="VALID",
             valence=2.7, branch="learned", partition_name="LEARNING")
    t += 60
    execution(log, episode_id=7000, ts=t, flag="DELAYED_FILL", delay=2)
    t += 60 * 8
    outcome(log, episode_id=7000, ts=t, net=6.25, close_reason="POLICY_CLOSE",
            held=8, trades=2)
    learning(log, episode_id=7000, valence=1, amount=0.00625)

    # ---- an outcome whose learning update was refused
    t += 60
    round_(log, i=8, ts=t)
    decision(log, episode_id=8000, ts=t, action="BUY", status="VALID",
             valence=2.9, branch="learned", partition_name="LEARNING")
    t += 60
    execution(log, episode_id=8000, ts=t)
    t += 120
    outcome(log, episode_id=8000, ts=t, net=-2.0, held=2, trades=3)
    learning(log, episode_id=8000, valence=-1, amount=0.002, accepted=False,
             reason="no eligible synapses", synapses=0)

    # ---- a decision whose optional telemetry was not recorded
    t += 60
    round_(log, i=9, ts=t)
    decision(log, episode_id=9000, ts=t, action="WAIT", status="VALID",
             valence=0.2, branch="learned", partition_name="LEARNING",
             telemetry=False)
    partition(log, "LEARNING", "end", branch="learned")
    return log


def frozen_branch() -> Log:
    """A FROZEN partition: outcomes settle, no LEARNING event is ever written.

    Both a loss and a gain, so "positive result — learning frozen" is a tested
    state and not an assumption.
    """
    log = Log()
    partition(log, "FROZEN", "start", branch="frozen_trained", learning=False)
    t = T0
    for n, net in ((1, -3.5), (2, +4.25)):
        round_(log, i=n, ts=t)
        decision(log, episode_id=n * 1000, ts=t, action="BUY", status="VALID",
                 valence=2.0, branch="frozen_trained",
                 partition_name="FROZEN")
        t += 60
        execution(log, episode_id=n * 1000, ts=t)
        t += 120
        outcome(log, episode_id=n * 1000, ts=t, net=net, held=2, frozen=True,
                trades=n)
        log.append("CHECKPOINT", {"episode_id": n * 1000, "digest": "f" * 64})
        t += 60
    partition(log, "FROZEN", "end", branch="frozen_trained")
    return log


def summary() -> dict:
    """A run summary in the shape ``experiments/*/summary.json`` has."""
    return {"run_id": "synthetic-001", "wave": "SYNTHETIC",
            "dataset_label": LABEL, "graph_sha256": "g" * 64,
            "selected_horizon_minutes": 5,
            "encoder": {"version": "synthetic-encoder",
                        "features": ["r1", "r5", "r20", "rv20", "relvol"],
                        "glomeruli": list(GLOM)},
            "decoder": {"version": "synthetic-decoder", "theta_hz": 0.9},
            "readout_learning": {"version": "synthetic-readout", "k": 8},
            "branches": {"learned": {}}}


def write_run(tmp_path, run_id: str = "synthetic-001") -> "object":
    """A whole run directory: two branches and a summary, all synthetic."""
    run = tmp_path / "runs" / run_id
    (run / "learned").mkdir(parents=True)
    (run / "frozen_trained").mkdir(parents=True)
    learning_branch().write(run / "learned" / "events.jsonl")
    frozen_branch().write(run / "frozen_trained" / "events.jsonl")
    import json as _json
    (tmp_path / "summary.json").write_text(_json.dumps(summary()))
    return run
