#!/usr/bin/env python
"""
The read-only presentation projection. Amendment D9(a) §8, addenda 3-5.

One canonical ``events.jsonl`` in, one ordered **presentation stream** out.
Nothing here decides, prices, decodes, reinforces or writes: every number a
frame carries was already a field of the event it came from, and the only
things this module computes are indices, counters, elapsed market minutes and
the pointers that make "the state as of event N" an array lookup instead of a
fold in the browser.

Why it exists (addendum 3). The browser must not own the domain semantics. The
distinctions amendment §4 insists on — a WAIT that was decoded against a
NO_RESPONSE that was not, a SELL *signal* against an executed sale, a neural
closure against a policy closure, a FROZEN settlement against a learning
update — are named branches **here**, in Python, under pytest. The page merges
frames and renders; it folds nothing.

## The stream

``project()`` returns ``{"meta": ..., "frames": [...]}``. There is exactly one
frame per line of the log, in file order, and a frame is::

    {"seq": 38,                  # the line index in events.jsonl. The
                                 # tie-break §5 asks for when two events share
                                 # a timestamp: file order, always.
     "ts": 1783345860,           # this event's own market timestamp, or null
                                 # when it carries none (CHECKPOINT, LEARNING,
                                 # PARTITION, WARMUP, RECOVERY)
     "kind": "DECISION",         # one of the ten canonical kinds
     "ev": {...},                # this event's small display payload
     "at": {...}}                # the state **after** this event

``at`` is a pure function of events ``0..seq``: it is produced by a single
forward pass and never looks ahead, so a cursor that has not reached an
outcome cannot be showing it, and seeking backwards is an index rather than a
replay. ``at`` carries *pointers* — the ``seq`` of the last DECISION, of the
EXECUTION still open, of the last OUTCOME, of the LEARNING that settled it —
so the page dereferences frames rather than accumulating anything.

## What it refuses to do

* it never opens ``brain.npz``, never imports :mod:`flytrade` (addendum 4: a
  worker startup path must not be reachable from the viewer), and never writes;
* it invents no starting balance, no mark-to-market and no PnL: the accounting
  block of a frame is the ``account`` sub-object the run wrote into its own
  ``OUTCOME`` event, copied;
* it reports optional telemetry that is absent as absent (``None``), and the
  page renders that as "unavailable" rather than as zero.
"""
from __future__ import annotations

import json
from pathlib import Path

#: the presentation contract's version. Bumped when a frame's shape changes.
CONTRACT = "flytrade-presentation-1"

# --------------------------------------------------------------- the kinds
# Duplicated from ``flytrade.records.EventType`` **on purpose** (addendum 4):
# importing it would pull ``runner`` and ``state`` into the viewer process.
# ``tests/observer/test_isolation.py`` imports the enum and asserts these two
# sets are equal, so the duplication cannot drift silently.
ROUND = "ROUND"
ROUND_ABORTED = "ROUND_ABORTED"
DECISION = "DECISION"
EXECUTION = "EXECUTION"
OUTCOME = "OUTCOME"
LEARNING = "LEARNING"
CHECKPOINT = "CHECKPOINT"
RECOVERY = "RECOVERY"
WARMUP = "WARMUP"
PARTITION = "PARTITION"
#: D10: one launch seen, with its admission reasons; and a position that could
#: not be settled. Neither existed before D10 and no log written before it
#: contains one, so every committed projection is unchanged by their addition.
DISCOVERY = "DISCOVERY"
UNRESOLVED = "UNRESOLVED"
#: D12: one relative-cohort lesson was applied in school mode. No log written
#: before D12 contains one, so every committed projection is unchanged by its
#: addition.
LESSON = "LESSON"
#: P1: the nine kinds the product feed writes (``flytrade.product.feed``). No
#: log written before P1 contains one, so every committed projection is
#: unchanged by their addition — as with DISCOVERY, UNRESOLVED and LESSON, the
#: vocabulary grows and the frames do not move.
SNIFF = "SNIFF"
PICK = "PICK"
OPEN = "OPEN"
MARK = "MARK"
CLOSE = "CLOSE"
CREDIT = "CREDIT"
HEARTBEAT = "HEARTBEAT"
THROTTLED = "THROTTLED"
RPC_ERROR = "RPC_ERROR"

KINDS = (ROUND, ROUND_ABORTED, DECISION, EXECUTION, OUTCOME, LEARNING,
         CHECKPOINT, RECOVERY, WARMUP, PARTITION, DISCOVERY, UNRESOLVED,
         LESSON, SNIFF, PICK, OPEN, MARK, CLOSE, CREDIT, HEARTBEAT, THROTTLED,
         RPC_ERROR)

# ------------------------------------------------------- readout vocabulary
# ``flytrade.decoder.ReadoutStatus`` and ``Action``, duplicated for the same
# reason and asserted equal by the same test.
VALID = "VALID"
NO_RESPONSE = "NO_RESPONSE"
INVALID_STATE = "INVALID_STATE"
POLICY_REJECT = "POLICY_REJECT"
READOUT_STATUSES = (VALID, NO_RESPONSE, INVALID_STATE, POLICY_REJECT)

BUY = "BUY"
SELL = "SELL"
WAIT = "WAIT"
ACTIONS = (BUY, SELL, WAIT, NO_RESPONSE)

#: one letter per replicate, so k = 8 statuses cost eight bytes in a frame
#: instead of eighty. The legend travels in ``meta`` and in CONTRACT.md.
STATUS_LETTER = {VALID: "V", NO_RESPONSE: "N", INVALID_STATE: "I",
                 POLICY_REJECT: "P"}
LETTER_STATUS = {v: k for k, v in STATUS_LETTER.items()}

#: the encoder's declared feature order (``summary.json`` ``encoder.features``).
#: Frames send the five values as a list in this order. D10 runs carry eight
#: differently named features and the pass reads their order off the first
#: observation it sees, falling back to these five — so a log written before
#: D10 projects to exactly the same bytes.
FEATURES = ("r1", "r5", "r20", "rv20", "relvol")

#: closure reasons the execution policy writes. A neural SELL and a horizon
#: expiry are different events and the viewer never merges them.
NEURAL_SELL = "NEURAL_SELL"
POLICY_CLOSE = "POLICY_CLOSE"
#: D9(b): the horizon expiry under the fixed-hold exit policy. It is a policy
#: closure — a timer, not a neural choice — and is counted with ``POLICY_CLOSE``
#: rather than given a counter of its own; the event itself keeps its own name,
#: so the screen still says which policy closed the position.
POLICY_CLOSE_FIXED_HOLD = "POLICY_CLOSE_FIXED_HOLD"
POLICY_CLOSURES = (POLICY_CLOSE, POLICY_CLOSE_FIXED_HOLD)
SESSION_CLOSE = "SESSION_CLOSE"

#: D9(b): the execution policy refused a decoded SELL because the position is
#: held to a fixed horizon. A blocked signal, never an executed sale.
FIXED_HOLD_REJECTION = "FIXED_HOLD"

#: the settlement marker ``Journal.settle_frozen`` writes. This — not the
#: branch name — is what makes a result "learning frozen" (addendum 9).
SETTLED_FROZEN = "SETTLED_FROZEN"

#: cumulative counters, in the order a frame's ``at.c`` list carries them.
COUNTERS = ("rounds", "rounds_no_decision", "decisions", "buy", "sell",
            "wait", "no_response", "invalid_state", "policy_reject",
            "executions", "outcomes", "neural_sell", "policy_close",
            "learning", "settled_frozen", "aborted", "warmup")


# ------------------------------------------------------------------ reading

def read_log(path) -> list[dict]:
    """Every line of a canonical log, in file order, parsed and untouched.

    A line that is not JSON becomes a ``TORN`` marker rather than an exception:
    an append-only log can end mid-write, and that is a state to display, not
    a crash.
    """
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                e = {"kind": "TORN", "raw": line[:200]}
            e["_i"] = i
            out.append(e)
    return out


def partition_spans(events: list[dict]) -> list[dict]:
    """``PARTITION`` boundaries as (name, first ``seq``, last ``seq``)."""
    spans: dict[str, dict] = {}
    for pos, e in enumerate(events):
        if e.get("kind") != PARTITION:
            continue
        i = e.get("_i", pos)
        name = e.get("partition", "?")
        s = spans.setdefault(name, {"partition": name, "start": i, "end": i,
                                    "events": 0})
        if e.get("boundary") == "start":
            s["start"] = i
        else:
            s["end"] = i
    for s in spans.values():
        s["events"] = s["end"] - s["start"] + 1
    return list(spans.values())


# ------------------------------------------------------------- the payloads

def _market_ts(e: dict):
    """The event's own market timestamp, or ``None`` when it has none.

    ``t`` is deliberately not consulted: it is the wall clock of the machine
    that ran the experiment, not market time, and showing one as the other is
    exactly the confusion §2A forbids.
    """
    for k in ("market_ts", "cutoff_ts"):
        v = e.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    if e.get("kind") in (EXECUTION, OUTCOME):
        v = e.get("ts")
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _r(x, n):
    """Round for display, preserving ``None``. Never a unit change."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return round(float(x), n)


def _features(obs, names=FEATURES) -> list | None:
    n = (obs or {}).get("normalized")
    if not isinstance(n, dict):
        return None
    return [_r(n.get(k), 4) for k in names]


def _feature_names(events) -> tuple[str, ...]:
    """The feature order this log actually wrote, or the five of D5-D9(b).

    A D10 decision states its order in ``feature_order``, because the
    observation dict is serialised with sorted keys and its order is therefore
    alphabetical rather than declared. A log without that field falls back to
    the dict's own keys, and one whose keys are the five D5-D9(b) features
    falls back to :data:`FEATURES` — so every earlier projection is unchanged.
    """
    for e in events:
        if e.get("kind") != DECISION:
            continue
        declared = e.get("feature_order")
        if isinstance(declared, list) and declared:
            return tuple(str(x) for x in declared)
        n = (e.get("observation") or {}).get("normalized")
        if isinstance(n, dict) and set(n) != set(FEATURES) and n:
            return tuple(n)
        if isinstance(n, dict) and n:
            return FEATURES
    return FEATURES


def _channels(stim) -> list[str]:
    r = (stim or {}).get("rates_hz")
    return sorted(r) if isinstance(r, dict) else []


def _rates(stim, channels) -> list | None:
    r = (stim or {}).get("rates_hz")
    if not isinstance(r, dict):
        return None
    return [_r(r.get(c), 2) for c in channels]


def _decision_payload(e: dict, channels: list[str],
                      names: tuple[str, ...] = FEATURES) -> dict:
    """What the watch screen shows for one DECISION.

    Every field is copied. The heavy ones the detail panel needs and the
    screen does not — ``observation.raw``, ``versions``, the digests — stay in
    the log and are fetched one event at a time from ``/api/detail``
    (addendum 5).
    """
    ro = e.get("readout") or {}
    pop = ro.get("population_sizes") or {}
    rates = ro.get("rates_hz") or {}
    sts = e.get("replicate_statuses")
    obs = e.get("observation") or {}
    return {
        "action": e.get("decoded_action"),
        "status": e.get("readout_status"),
        "observation_status": e.get("observation_status"),
        "symbol": e.get("symbol"),
        "episode_id": e.get("episode_id"),
        "close": _r(obs.get("close"), 4),
        "features": _features(obs, names),
        "glomeruli": _rates(e.get("stimulus"), channels),
        "n_orns": (e.get("stimulus") or {}).get("n_orns"),
        "total_drive_hz": _r((e.get("stimulus") or {}).get("total_drive_hz"), 1),
        "approach_hz": _r(rates.get("approach", e.get("approach_hz")), 4),
        "avoid_hz": _r(rates.get("avoid", e.get("avoid_hz")), 4),
        "pop": [pop.get("approach"), pop.get("avoid")] if pop else None,
        "kc_active": ro.get("kc_active"),
        "kc_fraction": _r(ro.get("kc_fraction"), 5),
        "max_rate_hz": _r(ro.get("max_rate_hz"), 2),
        "k": ro.get("k", e.get("k")),
        "silent_replicates": ro.get("silent_replicates"),
        "valence_hz": _r(e.get("valence_hz"), 4),
        "theta_hz": _r(e.get("theta_hz"), 4),
        "reps": (None if not isinstance(sts, list)
                 else "".join(STATUS_LETTER.get(s, "?") for s in sts)),
        "rep_scores": (None if not isinstance(e.get("replicate_scores"), list)
                       else [_r(v, 3) for v in e["replicate_scores"]]),
        "dataset_label": e.get("dataset_label"),
        # D9(b): which rule refused this action, when one did. Absent from
        # every log written before the field existed, and ``_compact`` drops
        # it, so the projections of the earlier runs are unchanged.
        "reject_reason": (e.get("rejection") or {}).get("reason"),
        "brain_cycle": e.get("brain_cycle"),
        "brain_ms": _r(e.get("brain_ms"), 0),
        # D10: the venue and chain identifiers, absent from every earlier log
        # and dropped by ``_compact`` when they are, so the committed D5-D9(b)
        # projections are byte-identical before and after this wave.
        "venue": e.get("venue"),
        "chain_id": e.get("chain_id"),
        "mode": e.get("mode"),
        "learning_mode": e.get("learning"),
        "token": e.get("token"),
        "curve": e.get("curve"),
        "block_number": e.get("block_number"),
        "age_s": e.get("age_s"),
        "marginal_price": e.get("marginal_price"),
        "last_trade_price": e.get("last_trade_price"),
        "executable_tokens_out": e.get("executable_tokens_out"),
    }


def _round_payload(e: dict) -> dict:
    cands = e.get("candidates") or []
    c0 = cands[0] if cands else {}
    return {"n_candidates": len(cands),
            "symbol": c0.get("symbol"),
            "observation_status": c0.get("status"),
            "silent_replicates": c0.get("silent_replicates"),
            "eligible": c0.get("eligible_union", c0.get("eligible")),
            "selected": e.get("selected_stable_id") is not None,
            "round_index": e.get("round_index"),
            # D10: the tick's own context and the open position's mark. The
            # mark is a mark: it is displayed, and it never reached learning.
            "venue": e.get("venue"), "mode": e.get("mode"),
            "learning_mode": e.get("learning"),
            "admitted": e.get("admitted"), "rotated": e.get("rotated"),
            "discovered": e.get("discovered"),
            "tracked": e.get("tracked"),
            "mark": e.get("mark"), "context": e.get("context")}


def _execution_payload(e: dict) -> dict:
    return {"side": e.get("side"), "symbol": e.get("symbol"),
            "episode_id": e.get("episode_id"),
            "fill_price": e.get("fill_price"),
            "reference_price": e.get("reference_price"),
            "quantity": e.get("quantity"), "fee": e.get("fee"),
            "slippage": e.get("slippage"), "value": e.get("value"),
            "flag": e.get("flag"), "delay_minutes": e.get("delay_minutes"),
            "bar_index": e.get("bar_index"), "k": e.get("k")}


def _outcome_payload(e: dict) -> dict:
    acc = e.get("account")
    return {"close_reason": e.get("close_reason"),
            "settlement": e.get("settlement"),
            "episode_id": e.get("episode_id"), "symbol": e.get("symbol"),
            "market_minutes_held": e.get("market_minutes_held"),
            "bars_held": e.get("bars_held"),
            "gross_reference_pnl": e.get("gross_reference_pnl"),
            "gross_pnl": e.get("gross_pnl"),
            "slippage": e.get("slippage"), "fees": e.get("fees"),
            "net_pnl": e.get("net_pnl"), "notional": e.get("notional"),
            "return_on_notional": e.get("return_on_notional"),
            "cumulative_realized_pnl": e.get("cumulative_realized_pnl"),
            "entry_flag": e.get("entry_flag"), "exit_flag": e.get("exit_flag"),
            "exit_price": (e.get("exit") or {}).get("fill_price"),
            "entry_price": (e.get("entry") or {}).get("fill_price"),
            "account": acc if isinstance(acc, dict) else None}


def _learning_payload(e: dict) -> dict:
    return {"accepted": e.get("accepted"), "valence": e.get("valence"),
            "amount": e.get("amount"), "reason": e.get("reason"),
            "episode_id": e.get("episode_id"), "k": e.get("k"),
            "normalisation": e.get("normalisation"),
            "eligibility_source": e.get("eligibility_source"),
            "synapses_depressed": e.get("synapses_depressed"),
            "trace_eligible": e.get("trace_eligible"),
            "depressed_per_replicate": e.get("depressed_per_replicate")}


def _compact(d: dict) -> dict:
    """Drop the keys whose value is ``None``.

    The contract (``observer/CONTRACT.md``) states the rule once: **a key that
    is absent from ``ev`` or ``at`` means the canonical field was absent or
    null**, and the page renders it as "unavailable" — never as zero. Dropping
    them is also what keeps the stream for ``d7-001/learned`` inside the
    payload budget of addendum 5.
    """
    return {k: v for k, v in d.items() if v is not None}


def _payload(e: dict, channels: list[str],
             names: tuple[str, ...] = FEATURES) -> dict:
    kind = e.get("kind")
    if kind == DISCOVERY:
        return _compact({"token": e.get("token"), "curve": e.get("curve"),
                         "admitted": e.get("admitted"),
                         "reasons": e.get("reasons"),
                         "launch_block": e.get("launch_block"),
                         "quote_asset": e.get("quote_asset"),
                         "venue": e.get("venue")})
    if kind == UNRESOLVED:
        return _compact({"episode_id": e.get("episode_id"),
                         "token": e.get("token"), "reason": e.get("reason"),
                         "detail": e.get("detail"), "settled": e.get("settled"),
                         "is_a_loss": e.get("is_a_loss"),
                         "venue": e.get("venue")})
    if kind == DECISION:
        return _compact(_decision_payload(e, channels, names))
    if kind == ROUND:
        return _compact(_round_payload(e))
    if kind == EXECUTION:
        return _compact(_execution_payload(e))
    if kind == OUTCOME:
        return _compact(_outcome_payload(e))
    if kind == LEARNING:
        return _compact(_learning_payload(e))
    if kind == LESSON:
        # D12: the cohort the signal came from, and the financial net beside
        # it — two columns, never merged.
        return _compact({"token": e.get("token"), "n": e.get("n"),
                         "rank": e.get("rank"), "s": e.get("s"),
                         "valence": e.get("valence"),
                         "amount": e.get("amount"),
                         "net_wei": e.get("net_wei"),
                         "accepted": e.get("accepted"),
                         "applied_at_tick": e.get("applied_at_tick"),
                         "digest": (e.get("checkpoint_digest_after") or "")[:12]
                         or None})
    if kind == PARTITION:
        return _compact({"partition": e.get("partition"), "boundary": e.get("boundary"),
                "branch": e.get("branch"), "learning": e.get("learning"),
                "neural": e.get("neural"), "rounds": e.get("rounds"),
                "state_digest": (e.get("state_digest") or "")[:12] or None,
                "run_id": e.get("run_id")})
    if kind == WARMUP:
        return _compact({"session": e.get("session"),
                "observations": e.get("observations"),
                "status_counts": e.get("status_counts"),
                "neural": e.get("neural"), "decisions": e.get("decisions"),
                "note": e.get("note")})
    if kind == CHECKPOINT:
        return _compact({"episode_id": e.get("episode_id"),
                         "digest": (e.get("digest") or "")[:12] or None})
    if kind == ROUND_ABORTED:
        return _compact({"reason": e.get("reason"), "replicate": e.get("replicate"),
                "round_index": e.get("round_index"),
                "stable_id": e.get("stable_id")})
    if kind == RECOVERY:
        return _compact({"action": e.get("action"),
                "checkpoint_loaded": e.get("checkpoint_loaded"),
                "episode_reopened": e.get("episode_reopened"),
                "pending_episode": e.get("pending_episode"),
                "reapplied": e.get("reapplied"),
                "last_settled_episode": e.get("last_settled_episode")})
    return {"raw": str(e.get("raw", ""))[:200]} if kind == "TORN" else {}


# -------------------------------------------------------------- the pass

def project(events: list[dict], *, horizon_minutes: int | None = None,
            horizon_source: str = "unavailable",
            meta_extra: dict | None = None) -> dict:
    """One forward pass: events in file order, frames out in the same order.

    ``horizon_minutes`` is the run's **maximum policy horizon** H, taken from
    that run's own summary by the caller and used for one thing only: the
    remaining-maximum-policy-horizon countdown of §4. It is never a promise
    that a position stays open that long — in ``d7-001/learned`` all 42
    positions closed on a neural SELL well before it.
    """
    channels: list[str] = []
    for e in events:                      # the encoder's glomerulus order,
        channels = _channels(e.get("stimulus"))   # read off the first
        if channels:                              # stimulus that exists
            break
    names = _feature_names(events)

    counts = dict.fromkeys(COUNTERS, 0)
    frames: list[dict] = []

    # the partitions are interned: ``at.p`` is an index into
    # ``meta.partition_table`` rather than a repeated object, which keeps the
    # per-frame cost of "which partition am I in" at three bytes.
    ptable: list[dict] = []
    pkey: dict[tuple, int] = {}
    partition = None          # index into ptable, or None before the first
    pending_round = None      # a ROUND whose DECISION has not arrived yet
    last_decision = last_round = None
    position = None           # seq of the EXECUTION whose position is open
    position_ts = None        # its market timestamp
    position_minutes: set = set()   # distinct market minutes since the fill
    last_outcome = last_learning = None
    last_settlement = None
    clock = None              # the market frontier: last market ts seen
    dataset_label = None
    index = {"decisions": [], "executions": [], "outcomes": [],
             "learning": [], "aborted": []}
    kind_counts: dict[str, int] = {}

    for pos, e in enumerate(events):
        seq = e.get("_i", pos)
        kind = e.get("kind")
        # "this round produced no decision" is settled by the event that
        # *follows* the round, never by looking ahead from the round itself:
        # at the round's own frame the answer is not yet in the record.
        if pending_round is not None and kind not in (DECISION, ROUND_ABORTED):
            counts["rounds_no_decision"] += 1
            pending_round = None
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        ts = _market_ts(e)
        if ts is not None:
            clock = ts
            if position is not None:
                position_minutes.add(ts)

        if kind == ROUND:
            counts["rounds"] += 1
            last_round = seq
            pending_round = seq

        elif kind == DECISION:
            pending_round = None
            counts["decisions"] += 1
            last_decision = seq
            index["decisions"].append(seq)
            st = e.get("readout_status")
            act = e.get("decoded_action")
            if st == VALID:
                counts["buy" if act == BUY else
                       "sell" if act == SELL else "wait"] += 1
            elif st == NO_RESPONSE:
                counts["no_response"] += 1
            elif st == INVALID_STATE:
                counts["invalid_state"] += 1
            elif st == POLICY_REJECT:
                counts["policy_reject"] += 1
            dataset_label = e.get("dataset_label") or dataset_label

        elif kind == EXECUTION:
            counts["executions"] += 1
            index["executions"].append(seq)
            position = seq
            position_ts = ts
            position_minutes = {ts} if ts is not None else set()

        elif kind == OUTCOME:
            counts["outcomes"] += 1
            index["outcomes"].append(seq)
            reason = e.get("close_reason")
            if reason == NEURAL_SELL:
                counts["neural_sell"] += 1
            elif reason in POLICY_CLOSURES:
                counts["policy_close"] += 1
            if e.get("settlement") == SETTLED_FROZEN:
                counts["settled_frozen"] += 1
            position = position_ts = None
            position_minutes = set()
            last_outcome = seq
            # the LEARNING event, when there is one, comes *after* this line.
            # Resetting the pointer here is what keeps the previous episode's
            # learning from being shown beside this episode's result.
            last_learning = None
            last_settlement = e.get("settlement")

        elif kind == LEARNING:
            counts["learning"] += 1
            index["learning"].append(seq)
            last_learning = seq

        elif kind == PARTITION:
            closed = e.get("boundary") != "start"
            # only the ``start`` boundary carries the partition's learning
            # flag; the ``end`` event repeats the name and the digest. The
            # flag is carried forward so "learning was on here" never becomes
            # "unavailable" at the moment a partition closes.
            was = ptable[partition]["learning"] if partition is not None \
                else None
            flag = e.get("learning")
            row = {"partition": e.get("partition"), "branch": e.get("branch"),
                   "learning": (was if flag is None and closed else flag),
                   "closed": closed}
            key = (row["partition"], row["branch"], row["learning"], closed)
            if key not in pkey:
                pkey[key] = len(ptable)
                ptable.append(row)
            partition = pkey[key]

        elif kind == WARMUP:
            counts["warmup"] += 1

        elif kind == ROUND_ABORTED:
            pending_round = None
            counts["aborted"] += 1
            index["aborted"].append(seq)

        held = None
        left = None
        if position is not None and position_ts is not None:
            held = max(0, len(position_minutes) - 1)
            if horizon_minutes is not None:
                left = max(0, int(horizon_minutes) - held)

        at = _compact({"ts": None if clock == ts else clock,
                       "p": partition,
                       "decision": last_decision,
                       "round": last_round,
                       "position": position,
                       "held": held,
                       "horizon_left": left,
                       "outcome": last_outcome,
                       "learning": last_learning,
                       "settlement": last_settlement})
        at["c"] = [counts[k] for k in COUNTERS]
        frames.append(_compact({"seq": seq, "ts": ts, "kind": kind,
                                "ev": _payload(e, channels, names) or None,
                                "at": at}))

    meta = {
        "contract": CONTRACT,
        "events": len(events),
        "frames": len(frames),
        "features": list(names),
        "channels": channels,
        "counters": list(COUNTERS),
        "replicate_legend": dict(LETTER_STATUS),
        "kinds": kind_counts,
        "kind_vocabulary": list(KINDS),
        "readout_statuses": list(READOUT_STATUSES),
        "actions": list(ACTIONS),
        "horizon_minutes": horizon_minutes,
        "horizon_source": horizon_source,
        "horizon_label": "remaining maximum policy horizon",
        "dataset_label": dataset_label,
        "first_ts": next((f["ts"] for f in frames if f.get("ts") is not None),
                         None),
        "last_ts": next((f["ts"] for f in reversed(frames)
                         if f.get("ts") is not None), None),
        "index": index,
        "partition_table": ptable,
        "partitions": partition_spans(events),
    }
    if meta_extra:
        meta.update(meta_extra)
    return {"meta": meta, "frames": frames}


# ---------------------------------------------------------------- provenance

def provenance(summary: dict | None) -> dict:
    """Run-level identity from ``summary.json``. Never an as-of value.

    Addendum 9: these keys are provenance for the identity strip and the
    record view — what graph, what encoder, what decoder, what readout policy
    — and must never be read as the state at the cursor.
    """
    s = summary or {}
    enc = s.get("encoder") or {}
    dec = s.get("decoder") or {}
    rl = s.get("readout_learning") or {}
    return {
        "run_id": s.get("run_id"),
        "wave": s.get("wave"),
        "dataset_label": s.get("dataset_label"),
        "graph_sha256": s.get("graph_sha256"),
        "clean_reference_digest": s.get("clean_reference_digest"),
        "encoder": enc.get("version"),
        "encoder_features": enc.get("features"),
        "glomeruli": enc.get("glomeruli"),
        "decoder": dec.get("version"),
        "theta_hz": dec.get("theta_hz"),
        "baseline_hz": dec.get("baseline_hz"),
        "max_kc_fraction": dec.get("max_kc_fraction"),
        "saturated_hz": dec.get("saturated_hz"),
        "readout": rl.get("version"),
        "k": rl.get("k"),
        "aggregation": rl.get("aggregation"),
        "branches": (sorted(s["branches"]) if isinstance(s.get("branches"),
                                                         dict) else None),
        "selected_horizon_minutes": s.get("selected_horizon_minutes"),
        "started_utc": s.get("started_utc"),
        "python": s.get("python"), "numpy": s.get("numpy"),
    }


def horizon_of(summary: dict | None) -> tuple[int | None, str]:
    """H and where it came from, or ``(None, "unavailable")``.

    D7 selected H on its WARMUP partition and stored it in ``registered-horizon-artifact``,
    which the run summary repeats as ``selected_horizon_minutes``. D5/D6 fixed
    it in ``config.execution.horizon_minutes``. When neither exists the viewer
    shows the horizon as unavailable and draws no countdown, rather than
    guessing a number that would look like a promise.
    """
    s = summary or {}
    v = s.get("selected_horizon_minutes")
    if isinstance(v, int):
        return v, "summary.selected_horizon_minutes"
    v = ((s.get("config") or {}).get("execution") or {}).get("horizon_minutes")
    if isinstance(v, int):
        return v, "summary.config.execution.horizon_minutes"
    return None, "unavailable"


def load(path, *, summary: dict | None = None) -> dict:
    """Read one branch's log and project all of it.

    The whole branch is always projected, never a partition slice: ``seq`` is
    then the file line index **and** the position of the frame in the stream,
    there is one identity for an event, and ``/api/detail?seq=`` asks for that
    line of that file. ``meta.partitions`` carries each partition's first and
    last ``seq`` so the page can jump to one without a second projection.
    """
    events = read_log(Path(path))
    h, src = horizon_of(summary)
    out = project(events, horizon_minutes=h, horizon_source=src)
    out["meta"]["provenance"] = provenance(summary)
    return out
