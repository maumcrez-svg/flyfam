"""The spectacle feed: one append-only day journal and one state file.

docs/SPEC.md P1 addendum 4. Two files under one directory, and they are the
whole contract GPT/Astra read (``docs/SPECTACLE_FEED.md`` documents them key by
key):

``events-YYYY-MM-DD.jsonl``  append-only, one JSON object per line, one file
                             per UTC day, never rewritten and never committed.
``state.json``               the current picture, rewritten **atomically after
                             every event** — write-temp-rename-fsync, so a
                             reader either sees the previous state or the new
                             one and never half of either.

This module writes; it decides nothing and computes no market quantity. The
loop hands it dictionaries that were computed by the objects that own them.

**No endpoint, no key, no PII.** Nothing here is ever given the RPC URL: the
only strings that reach it from the client are already masked by
:func:`flytrade.pons.rpc.mask`, and a test greps every file this module writes
for the endpoint, its host and its tokens.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..pons.budget import _atomic_write_json

VERSION = "pons-live-feed-1"
STATE_VERSION = "pons-live-state-1"

#: the kinds this feed writes. They are :class:`flytrade.records.EventType`
#: members too, so the observer's vocabulary and this one cannot drift.
SNIFF = "SNIFF"
PICK = "PICK"
OPEN = "OPEN"
MARK = "MARK"
CLOSE = "CLOSE"
CREDIT = "CREDIT"
HEARTBEAT = "HEARTBEAT"
THROTTLED = "THROTTLED"
RPC_ERROR = "RPC_ERROR"

KINDS = (SNIFF, PICK, OPEN, MARK, CLOSE, CREDIT, HEARTBEAT, THROTTLED,
         RPC_ERROR)

#: how many recent events ``state.json`` carries, and how many closed episodes.
#: The day journal is the history; the state file is a window on it.
KEEP_EVENTS = 200
KEEP_EPISODES = 100


def utc(epoch) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(epoch)))


def day_file(directory, epoch) -> Path:
    return Path(directory) / f"events-{time.strftime('%Y-%m-%d', time.gmtime(int(epoch)))}.jsonl"


class SpectacleFeed:
    """The two files. Append one line, rewrite one state, atomically."""

    version = VERSION

    def __init__(self, directory, *, run_id: str, stamp: dict | None = None,
                 now=None, keep_events: int = KEEP_EVENTS,
                 keep_episodes: int = KEEP_EPISODES):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = str(run_id)
        self.stamp = dict(stamp or {})
        self._now = now or time.time
        self.keep_events = int(keep_events)
        self.keep_episodes = int(keep_episodes)
        self.state_path = self.dir / "state.json"
        self.seq = 0
        self.counts: dict[str, int] = {}
        #: set by the runner: refreshes the state's sections from the live
        #: objects immediately before the file is written, so a reader that
        #: catches the file between two events sees an account and a position
        #: as current as the last line of the journal. It never emits.
        self.on_state = None
        self._writing = False
        self.state: dict = {
            "version": STATE_VERSION,
            "run_id": self.run_id,
            **self.stamp,
            "brain": {}, "account": {}, "position": None, "last_pick": None,
            "events": [], "episodes": [], "biggest_win": None,
            "biggest_loss": None, "rejected": {"session": {}, "last_hour": {}},
            "sniffed": {}, "requests": {}, "health": {}, "restore": {},
        }

    # --------------------------------------------------------------- resume
    def resume(self, state: dict) -> dict:
        """Carry a previous process's state forward. Returns what was carried.

        The sequence number, the event window, the closed-episode history, the
        extremes and the counters are the spectacle's memory: a restart that
        began them again at zero would be a different fly, and the point of
        the restart is that it is the same one.
        """
        carried = {}
        for key in ("events", "episodes", "biggest_win", "biggest_loss",
                    "rejected", "sniffed", "restore", "account", "position",
                    "last_pick"):
            if key in state:
                self.state[key] = state[key]
                carried[key] = True
        self.seq = int(state.get("seq", 0))
        self.counts = dict(state.get("kinds") or {})
        return carried

    # --------------------------------------------------------------- events
    def emit(self, kind: str, **fields) -> dict:
        """One event: appended to today's file, then the state rewritten."""
        if kind not in KINDS:
            raise ValueError(f"{kind!r} is not one of {KINDS}")
        now = self._now()
        self.seq += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        event = {"seq": self.seq, "ts": int(now), "utc": utc(now),
                 "kind": kind, "run_id": self.run_id, **self.stamp, **fields}
        path = day_file(self.dir, now)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        window = self.state.setdefault("events", [])
        window.append(self._for_state(event))
        del window[:-self.keep_events]
        self.write_state()
        return event

    @staticmethod
    def _for_state(event: dict) -> dict:
        """The event as the state window keeps it: whole, minus one list.

        ``state.json`` is rewritten after **every** event, and a ``SNIFF``
        carries up to 250 candidate rows — a window of two hundred of those is
        a half-megabyte file written ten times a tick, which is megabytes a
        minute of writes for a loop that is meant to run for weeks. The census
        counts and the reason histogram stay; the row list itself is dropped,
        because it is in the day file, whole, one line above.
        """
        if event.get("kind") != SNIFF or not event.get("candidates"):
            return event
        return {**event, "candidates": [],
                "candidates_in_the_day_file": len(event["candidates"])}

    # ---------------------------------------------------------------- state
    def update(self, **sections) -> None:
        """Replace whole named sections of the state. No merge, no surprise."""
        self.state.update(sections)

    def add_episode(self, episode: dict) -> None:
        """One closed episode: into the history, and into the two extremes."""
        history = self.state.setdefault("episodes", [])
        history.append(episode)
        del history[:-self.keep_episodes]
        net = episode.get("net_pnl_eth")
        if net is None:
            return
        best, worst = self.state.get("biggest_win"), self.state.get("biggest_loss")
        if net > 0 and (best is None or net > best.get("net_pnl_eth", 0.0)):
            self.state["biggest_win"] = episode
        if net < 0 and (worst is None or net < worst.get("net_pnl_eth", 0.0)):
            self.state["biggest_loss"] = episode

    def write_state(self) -> None:
        if self.on_state is not None and not self._writing:
            self._writing = True
            try:
                self.on_state()
            finally:
                self._writing = False
        now = self._now()
        self.state["seq"] = self.seq
        self.state["kinds"] = dict(self.counts)
        self.state["updated_epoch"] = int(now)
        self.state["updated_utc"] = utc(now)
        self.state["day_file"] = day_file(self.dir, now).name
        _atomic_write_json(self.state_path, self.state)

    # ----------------------------------------------------------- reading it
    @classmethod
    def read_state(cls, directory) -> dict | None:
        path = Path(directory) / "state.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:                                # pragma: no cover
            return None


__all__ = ["VERSION", "STATE_VERSION", "KINDS", "KEEP_EVENTS", "KEEP_EPISODES",
           "SNIFF", "PICK", "OPEN", "MARK", "CLOSE", "CREDIT", "HEARTBEAT",
           "THROTTLED", "RPC_ERROR", "SpectacleFeed", "day_file", "utc"]
