#!/usr/bin/env python
"""
The local observer's server. Amendment D6 §7 and Fable addendum 8.

    .venv/bin/python observer/serve.py            # http://localhost:8765/

Standard library only — ``http.server``, nothing else — **bound to 127.0.0.1**.
There is no public ingress, no external host, no upload, and no dataset is
exposed: the only market numbers that leave this process are the ones the
backend already wrote into its own canonical event log.

## What it serves

==========================  =============================================
``/``                       ``index.html``
``/api/runs``               the runs, branches and partitions on disk
``/api/summary?run=``       that run's ``summary.json``; for a D10 live run,
                            plus the ``health`` block the worker writes (cursor,
                            head, lag, requests, last error, ``fresh``, and the
                            worker's own liveness)
``/api/events?run=&branch=  the canonical events, optionally sliced to one
&partition=``               partition by its ``PARTITION`` boundary events
``/api/artifact?run=&name=  a committed read-only artifact of that run's wave:
``                          ``horizon`` (the D7 calibration and H*),
                            ``context`` (the D7 context-discrimination
                            summary), ``probes`` (the paired probe dataset),
                            ``learning`` (the D7 learning summary)
``/api/presentation?run=    D9(a): that branch's whole log projected into the
&branch=``                  presentation stream of ``observer/projection.py``
``/api/detail?run=&branch=  D9(a): **one** canonical event, the line ``seq``
&seq=``                     of that log, handed over unchanged
``/static/<name>``          D9(a): the viewer's own assets, by exact name from
                            an allowlist — no path from the client is ever
                            joined to a directory
==========================  =============================================

## What it does not do

It does not compute anything. It reads ``events.jsonl`` — the same append-only
file ``flytrade/records.py`` wrote during the run — parses each line as JSON
and hands it over unchanged. No field is derived, no PnL is recalculated, no
decision is re-decoded, and nothing is written back. If a number is on the
page it is because it is in the log.

The partition slice is a **line range**, found by scanning for the
``PARTITION`` events the run wrote at each boundary. Slicing by index cannot
change any event's content.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import projection as PJ            # noqa: E402  (read-only, stdlib only)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

#: every run store this observer can replay, newest wave last. A run id is
#: unique across them (``hist-NNN`` / ``d7-NNN``), so a run is found by its id
#: and its summary comes from its own experiment directory. D7 adds a second
#: root and three read-only artifacts; nothing else about the server changes.
ROOTS = (
    {"wave": "D5/D6",
     "runs": ROOT / "experiments" / "historical" / "runs",
     "summary": ROOT / "experiments" / "historical" / "summary.json",
     "extra": {}},
    {"wave": "D7",
     "runs": ROOT / "experiments" / "d7" / "runs",
     "summary": ROOT / "experiments" / "d7" / "frozen_summary.json",
     "extra": {"horizon": ROOT / "experiments" / "d7" / "registered-horizon-artifact",
               "context": ROOT / "experiments" / "d7" / "context_summary.json",
               "probes": ROOT / "experiments" / "d7" / "withheld-probe-table",
               "learning": ROOT / "experiments" / "d7" / "learning_summary.json"}},
    {"wave": "D9(b)",
     "runs": ROOT / "experiments" / "d9b" / "runs",
     "summary": ROOT / "experiments" / "d9b" / "frozen_summary.json",
     "extra": {"plan": ROOT / "experiments" / "d9b" / "config.json",
               "context": ROOT / "experiments" / "d9b" / "context_summary.json",
               "probes": ROOT / "experiments" / "d9b" / "withheld-probe-table",
               "alignment": ROOT / "experiments" / "d9b" / "alignment.json",
               "learning": ROOT / "experiments" / "d9b" / "learning_summary.json"}},
    # D10: the Pons wave. Its summary lives inside the run directory rather
    # than beside the experiment, because a D10 run is a run and not a
    # partition sweep; ``summary_for`` falls back to it.
    {"wave": "D10",
     "runs": ROOT / "experiments" / "d10" / "runs",
     "summary": ROOT / "experiments" / "d10" / "summary.json",
     "extra": {"plan": ROOT / "experiments" / "d10" / "config.json",
               "deployments": ROOT / "experiments" / "d10" / "deployments.json",
               "probes": ROOT / "experiments" / "d10" / "probe.json",
               "scales": ROOT / "experiments" / "d10" / "feature_scales_v2.json",
               "verification": ROOT / "experiments" / "d10" / "verification.json",
               "ledger": ROOT / "experiments" / "d10" / "rpc_ledger.json"}},
    # D11-001: the preregistered Pons learning evaluation. Same shape as D10 —
    # the summary lives inside the run directory — plus this wave's own
    # registration, its split, its node probe and its loopback ledger. A
    # finished run is a record of an hour that already ended, never a fly
    # operating now; `worker_alive` and `stop_reason` are already in
    # `/api/summary` and the page reads them.
    {"wave": "D11",
     "runs": ROOT / "experiments" / "d11" / "runs",
     "summary": ROOT / "experiments" / "d11" / "summary.json",
     "extra": {"plan": ROOT / "experiments" / "d11" / "config.json",
               "registration": ROOT / "experiments" / "d11" / "d11_001.json",
               "split": ROOT / "experiments" / "d11" / "split.json",
               "probes": ROOT / "experiments" / "d11" / "node_probe.json",
               "window": ROOT / "experiments" / "d11" / "window.json",
               "scales": ROOT / "experiments" / "d11" / "feature_scales_v2.json",
               "deployments": ROOT / "experiments" / "d10" / "deployments.json",
               "ledger": ROOT / "experiments" / "d11" / "rpc_ledger_local.json"}},
)

#: D10 addendum 13: what the viewer is told about a run, in the four terms the
#: amendment names. Read from the run's own summary; never guessed.
def wave_labels(run_id: str, summary: dict | None) -> dict:
    """``PONS / REPLAY|LIVE / PAPER / LEARN|FROZEN`` for a D10 run, else {}."""
    if not summary or summary.get("venue") != "PONS":
        return {}
    branches = summary.get("branches") or {}
    modes = sorted({b.get("mode", "") for b in branches.values()})
    learning = sorted({b.get("learning", "") for b in branches.values()})
    return {
        "venue": summary.get("venue"),
        "chain_id": summary.get("chain_id"),
        "data": ("LIVE" if any(m == "LIVE_PAPER" for m in modes) else "REPLAY"),
        "execution": "PAPER",
        "learning": learning,
        "modes": modes,
        "label": " / ".join([
            str(summary.get("venue")),
            "LIVE" if any(m == "LIVE_PAPER" for m in modes) else "REPLAY",
            "PAPER",
            "+".join(l for l in learning if l)]),
        # a live run's data is the live stream, not the recorded window the
        # replay run used; its label is in the run's own registration
        "dataset": ((summary.get("live") or {}).get("dataset_label")
                    or (summary.get("config") or {}).get("dataset", {}).get("label")),
    }

#: D10 addendum 15: a live run's worker writes this file once per tick, and
#: this process reads it. **The observer never opens a socket to the chain**:
#: every number below was written by the worker, and the only two things
#: computed here are ``fresh`` and the heartbeat's age, which are now-relative
#: by definition and are labelled as read-time facts.
FRESH_SECONDS = 120


def live_health(run_id: str) -> dict:
    """The live worker's health block for ``run_id``, or ``{}``.

    ``fresh`` is recomputed at read time from the worker's own
    ``confirmed_ts``: a health file written five minutes ago is not fresh
    however fresh it was when it was written, and a connection is not fresh
    data. ``worker_alive`` is the pid file plus the heartbeat's mtime — the
    server does not signal or inspect the process.
    """
    root = root_for(run_id)
    if not valid_id(run_id):
        return {}
    directory = root["runs"] / run_id
    path = directory / "health.json"
    if not path.is_file():
        return {}
    try:
        health = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    now = time.time()
    confirmed_ts = health.get("confirmed_ts")
    age = None if confirmed_ts is None else int(now - int(confirmed_ts))
    heartbeat_age = int(now - path.stat().st_mtime)
    pid = None
    pid_file = directory / "worker.pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text().split()[0])
        except (ValueError, IndexError):
            pid = None
    running = pid is not None
    if running:
        try:
            os.kill(pid, 0)
        except OSError:
            running = False
    return {**health,
            "confirmed_age_s": age,
            "fresh": bool(age is not None and age <= FRESH_SECONDS),
            "fresh_rule": (f"false whenever the last confirmed block is older "
                           f"than {FRESH_SECONDS} s: a connection is not fresh "
                           f"data"),
            "heartbeat_age_s": heartbeat_age,
            "worker": {"pid": pid, "alive": bool(running),
                       "pid_file": str(pid_file),
                       "heartbeat_file": str(path),
                       "heartbeat_age_s": heartbeat_age},
            "computed_at_read_time": ["fresh", "confirmed_age_s",
                                      "heartbeat_age_s", "worker.alive"]}


RUNS = ROOTS[0]["runs"]
SUMMARY = ROOTS[0]["summary"]


def root_for(run_id: str) -> dict:
    """The experiment directory a run id belongs to."""
    for r in ROOTS:
        if run_id and (r["runs"] / run_id).is_dir():
            return r
    return ROOTS[0]

#: 127.0.0.1 only. Not configurable to anything routable from this file.
HOST = "127.0.0.1"
PORT = 8765

#: D9(a) addendum 6 — the exposure boundary. The only files served off the
#: filesystem besides ``index.html`` are these, **by exact name**. The client's
#: string is a dictionary key, never a path component: there is no join, so
#: ``..``, an absolute path or a symlink have nothing to act on. Nothing here
#: is a dataset, a checkpoint, an event log or a configuration file.
STATIC = {
    "watch.css": "text/css; charset=utf-8",
    "NOTICE": "text/plain; charset=utf-8",
}
STATIC_DIR = HERE / "static"


def valid_id(s: str) -> bool:
    """A run or branch id: letters, digits, dash, underscore, dot. No slash.

    Ids are looked up against the set discovered on disk as well; this is the
    cheap first gate that keeps a traversal attempt from ever reaching a
    ``Path`` join.
    """
    return bool(s) and len(s) < 128 and all(
        c.isalnum() or c in "-_." for c in s) and ".." not in s


def find_log(run: str, branch: str) -> Path | None:
    """The event log of ``run``/``branch``, or ``None``.

    Both ids are validated and then matched against what ``list_runs()``
    actually found, so an unknown id is a 404 rather than a filesystem probe.
    """
    if not (valid_id(run) and valid_id(branch)):
        return None
    for r in list_runs():
        if r["run_id"] != run:
            continue
        for b in r["branches"]:
            if b["branch"] == branch:
                log = root_for(run)["runs"] / run / branch / "events.jsonl"
                return log if log.is_file() else None
    return None


def summary_for(run: str) -> dict | None:
    """That run's wave summary, parsed, or ``None`` when it is not written.

    D10 writes its summary inside the run directory, so that is tried first and
    the wave-level file is the fallback. Nothing else about the lookup changes.
    """
    root = root_for(run)
    for p in ((root["runs"] / run / "summary.json") if valid_id(run) else None,
              root["summary"]):
        if p is None or not p.exists():
            continue
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


def is_journal(log: Path) -> bool:
    """Is this ``events.jsonl`` a **journal**, or some other append-only log?

    D10 keeps a run's chain evidence beside its journal, and the collector's
    normalised events also live in a file called ``events.jsonl``. They are not
    records: a journal line carries a ``kind`` from the projection's own
    vocabulary and a chain line carries an ``event``, a ``source`` and a
    ``log_id``. One line is enough to tell them apart, and a directory that
    fails the test is not offered to the viewer as a branch.
    """
    try:
        with open(log, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                return json.loads(line).get("kind") in PJ.KINDS
    except (OSError, json.JSONDecodeError):
        return False
    return False


def list_runs() -> list[dict]:
    out = []
    for root in ROOTS:
        if not root["runs"].exists():
            continue
        for d in sorted(root["runs"].iterdir()):
            if not d.is_dir():
                continue
            branches = []
            for b in sorted(d.iterdir()):
                log = b / "events.jsonl"
                if b.is_dir() and log.exists() and is_journal(log):
                    branches.append({
                        "branch": b.name,
                        "bytes": log.stat().st_size,
                        "partitions": partitions_in(log)})
            note = (d / "WHAT_THIS_IS.txt")
            row = {"run_id": d.name, "wave": root["wave"],
                   "branches": branches,
                   "artifacts": sorted(k for k, p in root["extra"].items()
                                       if p.exists()),
                   "note": note.read_text() if note.exists() else ""}
            # D10 addendum 13: PONS / REPLAY|LIVE / PAPER / LEARN|FROZEN, read
            # off the run's own summary. Absent for every earlier wave, so
            # their rows are unchanged.
            labels = wave_labels(d.name, summary_for(d.name)
                                 if root["wave"] == "D10" else None)
            if labels:
                row["pons"] = labels
            out.append(row)
    return out


def partitions_in(log: Path) -> list[dict]:
    """The PARTITION boundary events, as (name, first index, last index)."""
    spans: dict[str, dict] = {}
    with open(log, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if '"PARTITION"' not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") != "PARTITION":
                continue
            name = e.get("partition", "?")
            s = spans.setdefault(name, {"partition": name, "start": i,
                                        "end": i, "events": 0})
            if e.get("boundary") == "start":
                s["start"] = i
            else:
                s["end"] = i
    for s in spans.values():
        s["events"] = s["end"] - s["start"] + 1
    return list(spans.values())


def read_events(log: Path, start: int | None, end: int | None,
                limit: int) -> list[dict]:
    out = []
    with open(log, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if start is not None and i < start:
                continue
            if end is not None and i > end:
                break
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                e = {"kind": "TORN", "raw": line[:200]}
            e["_i"] = i
            out.append(e)
            if len(out) >= limit:
                break
    return out


#: the projected streams already built, keyed by (path, size, mtime). A branch
#: is projected once per process and reused; the projection is pure, so a cache
#: hit and a cold read are the same bytes. Addendum 5: heavy work stays on this
#: side of the wire and off the render loop.
_CACHE: dict[tuple, bytes] = {}


def presentation_bytes(log: Path, summary: dict | None) -> bytes:
    st = log.stat()
    key = (str(log), st.st_size, st.st_mtime_ns)
    hit = _CACHE.get(key)
    if hit is None:
        hit = json.dumps(PJ.load(log, summary=summary),
                         separators=(",", ":")).encode()
        _CACHE.clear()               # one branch at a time; never unbounded
        _CACHE[key] = hit
    return hit


class Handler(BaseHTTPRequestHandler):
    server_version = "flytrade-observer/1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        head = {}
        # gzip only when the client asked for it. The presentation stream of
        # d7-001/learned is 4.3 MB of JSON and 0.55 MB compressed; this is the
        # difference between a page that opens and a page that waits.
        if (len(body) > 4096
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            body = gzip.compress(body, 6)
            head["Content-Encoding"] = "gzip"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in head.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:                      # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        one = lambda k, d=None: (q.get(k) or [d])[0]     # noqa: E731

        if u.path in ("/", "/index.html"):
            p = HERE / "index.html"
            return self._send(200, p.read_bytes(), "text/html; charset=utf-8")

        if u.path == "/api/runs":
            return self._json({"runs": list_runs(),
                               "summary_present": SUMMARY.exists()})

        if u.path == "/api/summary":
            run = one("run", "")
            root = root_for(run)
            body = summary_for(run)
            if body is None:
                return self._json(
                    {"error": f"{root['summary'].name} is not written yet"},
                    404)
            labels = wave_labels(run, body)
            if labels:
                body = {**body, "pons": labels}
            health = live_health(run)
            if health:
                # D10 addendum 15: the live health block, from the files the
                # worker writes. Nothing here reaches the chain.
                body = {**body, "health": health, "fresh": health["fresh"]}
            return self._json(body)

        if u.path == "/api/artifact":
            # D7: the calibration artifact, the probe dataset and the context
            # summary, served exactly as they are on disk. The page displays
            # them; it does not recompute a single field of either.
            root = root_for(one("run", ""))
            name = one("name", "")
            p = root["extra"].get(name)
            if p is None:
                return self._json(
                    {"error": f"no artifact {name!r} for this run",
                     "available": sorted(root["extra"])}, 404)
            if not p.exists():
                return self._json({"error": f"{p.name} is not written yet"},
                                  404)
            return self._send(200, p.read_bytes(), "application/json")

        if u.path == "/api/events":
            run = one("run", "")
            branch = one("branch", "learned")
            log = root_for(run)["runs"] / run / branch / "events.jsonl"
            if not log.exists():
                return self._json({"error": f"no event log at {log}"}, 404)
            start = end = None
            part = one("partition")
            if part:
                for s in partitions_in(log):
                    if s["partition"] == part:
                        start, end = s["start"], s["end"]
                        break
                if start is None:
                    return self._json(
                        {"error": f"no PARTITION events for {part!r}"}, 404)
            if one("from"):
                start = int(one("from"))
            if one("to"):
                end = int(one("to"))
            limit = int(one("limit", "200000"))
            ev = read_events(log, start, end, limit)
            return self._json({"run": run, "branch": branch,
                               "partition": part, "from": start, "to": end,
                               "count": len(ev), "events": ev})

        if u.path == "/api/presentation":
            # D9(a) addendum 3: the whole branch, projected server-side into
            # the presentation stream. The browser merges frames; it folds no
            # domain state and computes no money.
            run, branch = one("run", ""), one("branch", "")
            log = find_log(run, branch)
            if log is None:
                return self._json(
                    {"error": "no such run/branch on disk",
                     "run": run, "branch": branch,
                     "state": "MISSING_DATA"}, 404)
            body = presentation_bytes(log, summary_for(run))
            return self._send(200, body, "application/json")

        if u.path == "/api/detail":
            # one canonical event, unchanged: the heavy fields the watch
            # screen does not carry (observation.raw, versions, digests, the
            # per-replicate arrays) on demand, one line at a time.
            run, branch = one("run", ""), one("branch", "")
            log = find_log(run, branch)
            if log is None:
                return self._json({"error": "no such run/branch on disk"}, 404)
            try:
                seq = int(one("seq", ""))
            except (TypeError, ValueError):
                return self._json({"error": "seq must be an integer"}, 400)
            if seq < 0:
                return self._json({"error": "seq must not be negative"}, 400)
            ev = read_events(log, seq, seq, 1)
            if not ev:
                return self._json({"error": f"no event at line {seq}"}, 404)
            return self._json({"run": run, "branch": branch, "seq": seq,
                               "event": ev[0]})

        if u.path.startswith("/static/"):
            # the allowlist is a dictionary lookup on the exact remainder.
            # Nothing the client sends is ever joined to a directory.
            name = u.path[len("/static/"):]
            ctype = STATIC.get(name)
            if ctype is None:
                return self._json({"error": "not found"}, 404)
            p = STATIC_DIR / name
            if not p.is_file():
                return self._json({"error": f"{name} is not on disk"}, 404)
            return self._send(200, p.read_bytes(), ctype)

        self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):             # quieter console
        sys.stderr.write("  %s\n" % (fmt % args))


def main(argv) -> int:
    port = int(argv[1]) if len(argv) > 1 else PORT
    srv = ThreadingHTTPServer((HOST, port), Handler)
    print(f"observer on http://{HOST}:{port}/   (local only; Ctrl-C to stop)")
    for r in ROOTS:
        print(f"reading {r['runs']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
