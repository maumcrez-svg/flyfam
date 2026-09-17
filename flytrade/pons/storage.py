"""Canonical local storage for chain evidence: raw logs, normalised events, cursor.

docs/SPEC.md D10 addenda 5 and 6. Four files under a run's ``chain/``
directory:

``raw.jsonl``      every log exactly as the endpoint delivered it, including
                   the ones later orphaned. Never rewritten, never deleted.
``events.jsonl``   the normalised events, plus ``ORPHANED`` markers that name
                   the log ids a reorg invalidated. Append-only, so the history
                   of what we believed and when stays readable.
``headers.jsonl``  block headers, by hash, for the timestamps and for checking
                   that a stored block still exists on the chain we see.
``cursor.json``    the durable cursor, written temp-rename-fsync.

Append-only JSONL plus one atomically replaced pointer is the same discipline
as the existing checkpoints: a kill at any instant leaves a readable prefix.
:meth:`ChainStore.load` truncates a torn trailing line rather than pretending
it parsed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .budget import _atomic_write_json

CURSOR_VERSION = "d10-cursor-1"


def log_id(raw: dict) -> str:
    """The donor's ``logId``: block hash, transaction hash, log index.

    Block hash rather than block number, so the same log delivered on two
    competing branches is two ids and a reorg cannot silently overwrite.
    """
    return (f"{str(raw['blockHash']).lower()}:{str(raw['transactionHash']).lower()}"
            f":{int(str(raw['logIndex']), 16)}")


def order_key(raw: dict) -> tuple[int, int, int]:
    return (int(str(raw["blockNumber"]), 16),
            int(str(raw["transactionIndex"]), 16),
            int(str(raw["logIndex"]), 16))


def event_order_key(event: dict) -> tuple[int, int, int]:
    return (int(event["block_number"]), int(event["tx_index"]),
            int(event["log_index"]))


def _append_jsonl(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, dropping and truncating a torn trailing line."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    complete = raw.rsplit(b"\n", 1)
    body, tail = (complete[0], complete[1]) if len(complete) == 2 else (b"", raw)
    if tail:  # a line without its newline: the process died mid-append
        with open(path, "r+b") as fh:
            fh.truncate(len(body) + (1 if body else 0))
            fh.flush()
            os.fsync(fh.fileno())
    out = []
    for line in body.splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


class ChainStore:
    """The four files, the dedup set, the orphan set and the cursor."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.raw_path = self.directory / "raw.jsonl"
        self.events_path = self.directory / "events.jsonl"
        self.headers_path = self.directory / "headers.jsonl"
        self.cursor_path = self.directory / "cursor.json"
        self.seen: set[str] = set()
        self.orphaned: set[str] = set()
        self.events: list[dict] = []
        self.headers: dict[str, dict] = {}
        self.headers_by_number: dict[int, dict] = {}
        self.cursor: dict | None = None

    # ---------------------------------------------------------------- load
    def load(self) -> "ChainStore":
        for record in _read_jsonl(self.raw_path):
            self.seen.add(record["log_id"])
        for record in _read_jsonl(self.events_path):
            if record.get("kind") == "ORPHANED":
                self.orphaned.update(record.get("log_ids", ()))
            else:
                self.events.append(record)
        for header in _read_jsonl(self.headers_path):
            self.headers[header["hash"]] = header
            self.headers_by_number[int(header["number"])] = header
        if self.cursor_path.exists():
            self.cursor = json.loads(self.cursor_path.read_text(encoding="utf-8"))
        return self

    # -------------------------------------------------------------- writes
    def record_raw(self, raws: list[dict], *, received_at: str) -> list[dict]:
        """Persist the logs we have not seen before. Returns the new ones."""
        fresh = []
        for raw in raws:
            ident = log_id(raw)
            if ident in self.seen:
                continue
            self.seen.add(ident)
            fresh.append({"log_id": ident, "received_at": received_at, "log": raw})
        _append_jsonl(self.raw_path, fresh)
        return [entry["log"] for entry in fresh]

    def record_headers(self, headers: list[dict]) -> None:
        fresh = []
        for header in headers:
            key = str(header["hash"]).lower()
            if key in self.headers:
                continue
            entry = {"number": int(str(header["number"]), 16)
                     if str(header["number"]).startswith("0x") else int(header["number"]),
                     "hash": key,
                     "parentHash": str(header["parentHash"]).lower(),
                     "timestamp": int(str(header["timestamp"]), 16)
                     if str(header["timestamp"]).startswith("0x")
                     else int(header["timestamp"])}
            self.headers[key] = entry
            self.headers_by_number[entry["number"]] = entry
            fresh.append(entry)
        _append_jsonl(self.headers_path, fresh)

    def record_events(self, events: list[dict]) -> None:
        known = {e["log_id"] for e in self.events}
        fresh = [e for e in events if e["log_id"] not in known]
        self.events.extend(fresh)
        _append_jsonl(self.events_path, fresh)

    def orphan(self, log_ids, *, at_block: int, reason: str) -> list[str]:
        """Mark events invalid. The raw logs stay; the events stop counting."""
        new = [i for i in log_ids if i not in self.orphaned]
        if not new:
            return []
        self.orphaned.update(new)
        _append_jsonl(self.events_path, [{
            "kind": "ORPHANED", "log_ids": sorted(new),
            "at_block": int(at_block), "reason": str(reason)}])
        return sorted(new)

    def save_cursor(self, *, chain_id: int, block_number: int, block_hash: str,
                    tx_index: int, log_index: int, confirmed_block: int | None,
                    confirmed_hash: str | None) -> dict:
        cursor = {
            "version": CURSOR_VERSION,
            "chain_id": int(chain_id),
            "block_number": int(block_number),
            "block_hash": str(block_hash).lower(),
            "tx_index": int(tx_index),
            "log_index": int(log_index),
            "confirmed_block": None if confirmed_block is None else int(confirmed_block),
            "confirmed_hash": None if confirmed_hash is None else str(confirmed_hash).lower(),
        }
        _atomic_write_json(self.cursor_path, cursor)
        self.cursor = cursor
        return cursor

    # ------------------------------------------------------------- queries
    def live_events(self) -> list[dict]:
        """Every normalised event a reorg has not invalidated, in chain order."""
        return sorted((e for e in self.events if e["log_id"] not in self.orphaned),
                      key=event_order_key)

    def header_at_or_below(self, number: int) -> dict | None:
        """The stored header nearest at or below ``number``. No request.

        Reviewer decision 2: headers are sparse, so "the header of block n" is
        usually not on disk and "the grid anchor below n" is. Used by the
        cursor's confirmed marker and by the confirmation re-read.
        """
        number = int(number)
        best = None
        for stored in self.headers_by_number.values():
            n = int(stored["number"])
            if n <= number and (best is None or n > int(best["number"])):
                best = stored
        return best

    def events_in_blocks(self, numbers) -> list[dict]:
        numbers = {int(n) for n in numbers}
        return [e for e in self.events if int(e["block_number"]) in numbers]
