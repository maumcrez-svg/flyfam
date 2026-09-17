#!/usr/bin/env python
"""Write ``brains/trader-v1/`` — the frozen trader, and its manifest.

    .venv/bin/python product/freeze.py [--force]

P1 addendum 2. The trader is the **clean reference** of `d11-001`/`d12-001`,
digest ``ba95b605…``: the checkpoint the school started from and the one
`frozen_reference` reproduced to the wei. It is constructed here the way
``experiments/d11/common.py::build_brain`` constructs it — the same graph, the
same annotations, every plastic KC->MBON gain at 1.0 — and the construction
refuses to continue unless the graph sha256 and the state digest are the two
the D11 configuration registered before any D11 number existed.

**Provenance is verified before anything is written.** The gains and positions
of the checkpoints `d11-001/frozen_reference/brain.npz` and
`d12-001/frozen_reference/brain.npz` are compared element by element with the
constructed ones, and their digest with the registered one. The artifact is
therefore the same learned state those two branches ended with, and the
comparison is recorded in the manifest rather than asserted.

What the artifact does **not** carry is those branches' bookkeeping: their
``episode`` counter (the last episode each settled) and their credit counters.
A product journal that loaded them would read a D12 experiment's episode ids
as its own settled markers. The checkpoint is written with ``episode = -1`` and
empty counters, which is what a journal that has settled nothing means.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(ROOT / "upstream"), str(ROOT / "experiments" / "d11")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as C                                      # noqa: E402 (D11's)
from flytrade import state as S                         # noqa: E402

OUT = ROOT / "brains" / "trader-v1"
D11_CONFIG = ROOT / "experiments" / "d11" / "config.json"

#: the two checkpoints the artifact's weights are compared against, element by
#: element, before anything is written
PROVENANCE = (
    ("d11-001/frozen_reference",
     ROOT / "experiments/d11/runs/d11-001/frozen_reference/brain.npz"),
    ("d12-001/frozen_reference",
     ROOT / "experiments/d12/runs/d12-001/frozen_reference/brain.npz"),
)


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
    except Exception:                                    # pragma: no cover
        return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="rewrite an artifact that already exists")
    args = parser.parse_args(argv)

    cfg_v2 = json.loads(D11_CONFIG.read_text())
    registered = cfg_v2["next_run"]["clean_reference_checkpoint"]
    fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(cfg_v2)
    gain = np.ascontiguousarray(mb.gain, dtype=np.float32)
    pos = np.ascontiguousarray(mb.pos, dtype=np.int64)
    assert clean == registered["state_digest"], "build_brain let a digest through"
    assert sha == registered["graph_sha256"]
    assert len(pos) == int(registered["plastic_synapses"])
    assert float(gain.min()) == float(gain.max()) == float(registered["gain"])

    provenance = []
    for name, path in PROVENANCE:
        if not path.exists():
            provenance.append({"run_branch": name, "path": str(path.relative_to(ROOT)),
                               "present": False})
            continue
        z = np.load(path, allow_pickle=False)
        same_gain = bool(np.array_equal(z["gain"].astype(np.float32), gain))
        same_pos = bool(np.array_equal(z["pos"].astype(np.int64), pos))
        digest = S._digest(z["gain"].astype(np.float32),
                           z["pos"].astype(np.int64), str(z["graph_sha256"]))
        if not (same_gain and same_pos and digest == clean):
            raise SystemExit(f"{name} is not the clean reference: the artifact "
                             f"is not written")
        provenance.append({
            "run_branch": name, "path": str(path.relative_to(ROOT)),
            "present": True, "gain_identical": same_gain,
            "pos_identical": same_pos, "state_digest": digest,
            "episode_counter_in_that_checkpoint": int(z["episode"]),
            "note": ("the weights are identical; that branch's own episode "
                     "counter and credit counters are not carried into the "
                     "artifact")})

    OUT.mkdir(parents=True, exist_ok=True)
    checkpoint = OUT / "brain.npz"
    if checkpoint.exists() and not args.force:
        raise SystemExit(f"{checkpoint} exists; --force to rewrite")
    S.save_checkpoint(checkpoint, gain=gain, pos=pos, graph_sha256=sha,
                      rng_seed=0, episode=-1,
                      events={"accepted": 0, "settled": 0, "open": [],
                              "rejections": {}, "rejections_total": 0,
                              **encoder.schema_metadata()})
    back = S.load_checkpoint(checkpoint, graph_sha256=sha, expect_pos=pos)
    digest = S._digest(back["gain"], back["pos"], back["graph_sha256"])
    if digest != clean:
        raise SystemExit("the written checkpoint does not load to the "
                         "registered digest")

    manifest = {
        "artifact": "trader-v1",
        "what": ("the frozen trader of the P1 product wave: the clean "
                 "reference brain of d11-001/d12-001, learning FROZEN"),
        "spec": ("docs/SPEC.md, P1 owner decision (2026-09-13) and Fable "
                 "addendum 2"),
        "learning": "FROZEN",
        "never": ("no plasticity is applied in the product loop; a settled "
                  "episode is recorded as a CREDIT event and changes no weight"),
        "state_digest": clean,
        "graph_sha256": sha,
        "plastic_synapses": int(len(pos)),
        "gain": {"min": float(gain.min()), "max": float(gain.max()),
                 "mean": float(gain.mean()),
                 "note": "every plastic KC->MBON gain at the ceiling 1.0: "
                         "never depressed by any lesson"},
        "encoder": {"version": encoder.version,
                    "input_schema_sha256": encoder.input_schema_sha256,
                    "features": list(encoder.features)},
        "d11_config": {"path": "experiments/d11/config.json",
                       "sha256": sha256_file(D11_CONFIG)},
        "checkpoint": {"path": "brains/trader-v1/brain.npz",
                       "schema": str(back["schema"]),
                       "episode": int(back["episode"]),
                       "episode_meaning": ("last settled episode; -1 is "
                                           "'this brain has settled nothing'"),
                       "sha256": sha256_file(checkpoint),
                       "sha256_is_the_file_as_committed": (
                           "an .npz is a zip and carries per-entry mtimes, so "
                           "rebuilding it gives a different file hash for the "
                           "same weights; the identity of this brain is "
                           "state_digest, and this hash is a tamper check on "
                           "the committed file")},
        "provenance": {
            "run_ids": ["d10-001", "d11-001", "d12-001"],
            "declared_in": [
                "experiments/d11/config.json next_run.clean_reference_checkpoint",
                "experiments/d12/runs/d12-001/report.md",
                "the session log 2026-09-13 (m)"],
            "checkpoints_compared": provenance,
            "spec_commit": "f207679",
            "head_commit_at_build": git("rev-parse", "--short=12", "HEAD"),
            "built_by": "product/freeze.py",
        },
        "wei_exact_replay_is_not_repeated_here": (
            "d12-001's frozen_reference branch already reproduced d11-001 to "
            "the wei (+0.00511362 ETH, digest unchanged); addendum 2 says that "
            "proof is not repeated"),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {checkpoint} and {OUT / 'manifest.json'}")
    print(f"digest {clean}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
