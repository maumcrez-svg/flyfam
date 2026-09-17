#!/usr/bin/env python
"""Did the second execution of a branch reproduce the first, byte for byte?

    .venv/bin/python experiments/d10/determinism.py A/events.jsonl B/events.jsonl

Two fields cannot be reproduced by a second process **by construction** and are
removed before the comparison, which is why this file exists instead of a bare
`sha256sum`:

* ``t`` — the wall clock :class:`flytrade.records.EventLog` stamps on every
  line. A second run happens at a different time; that is the whole of the
  difference.
* the checkpoint's absolute ``path``, which contains the run directory.

Everything else — every seed, every measurement, every decision digest, every
fill, every learning event and the final state digest — must be identical, and
this prints the first difference if it is not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VOLATILE = ("t", "path")


def normalise(line: str) -> str:
    record = json.loads(line)
    for key in VOLATILE:
        record.pop(key, None)
    return json.dumps(record, sort_keys=True)


def digest(path: Path) -> tuple[str, int, list[str]]:
    rows = [normalise(line) for line in path.read_text().splitlines()
            if line.strip()]
    h = hashlib.sha256()
    for row in rows:
        h.update(row.encode())
        h.update(b"\n")
    return h.hexdigest(), len(rows), rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("--first-digest", default=None)
    parser.add_argument("--second-digest", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    a_sha, a_n, a_rows = digest(Path(args.first))
    b_sha, b_n, b_rows = digest(Path(args.second))
    first_difference = None
    for i, (x, y) in enumerate(zip(a_rows, b_rows)):
        if x != y:
            first_difference = {"line": i, "first": x[:400], "second": y[:400]}
            break
    report = {
        "first": args.first, "second": args.second,
        "lines": a_n, "lines_second": b_n,
        "normalised_sha256": a_sha, "normalised_sha256_second": b_sha,
        "removed_fields": list(VOLATILE),
        "removed_why": ("the wall clock every event line carries and the "
                        "absolute checkpoint path; a second process cannot "
                        "reproduce either by construction"),
        "log_identical": a_sha == b_sha and a_n == b_n,
        "first_difference": first_difference,
        "digest_identical": (None if args.first_digest is None
                             else args.first_digest == args.second_digest),
        "final_digest": args.first_digest,
        "final_digest_second": args.second_digest,
    }
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0 if report["log_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
