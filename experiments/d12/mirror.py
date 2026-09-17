#!/usr/bin/env python
"""The mirror diagnostic on the **existing** d11-001 scores. Step (iii).

    .venv/bin/python experiments/d12/mirror.py

Fable addendum 5, and the owner's own request: *"uma conta barata sobre os
scores já existentes para saber se o cérebro treinado virou aproximadamente o
negativo do cérebro virgem"*. It reads two files `d11-001` already wrote —
``grid/scores_trained.jsonl`` and ``grid/scores_reference.jsonl`` — runs no
brain, opens no socket, and writes ``experiments/d12/mirror_diagnostic.md``
beside ``mirror_diagnostic.json``.

**Wording: numbers.** The mechanistic reading — fifteen punishments depressed
the approach pathway in proportion to the prior valence, so the trained valence
is a decreasing affine function of the untrained one — is a **hypothesis** that
the slope ``b`` and Kendall ``tau`` test. It is not a finding until the owner
states it as one.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import d12lib as L                                        # noqa: E402
import stats as ST                                        # noqa: E402  (D11's)

C = L.C


# ------------------------------------------------------------ primitives
def _inversions(values) -> int:
    """Discordant pairs of a sequence, by merge sort. O(n log n), exact."""
    arr = list(values)
    if len(arr) < 2:
        return 0
    buf = [0] * len(arr)
    count = 0

    def sort(lo, hi):
        nonlocal count
        if hi - lo < 2:
            return
        mid = (lo + hi) // 2
        sort(lo, mid)
        sort(mid, hi)
        i, j, k = lo, mid, lo
        while i < mid and j < hi:
            if arr[i] <= arr[j]:
                buf[k] = arr[i]
                i += 1
            else:
                count += mid - i          # arr[i:mid] all beat arr[j]
                buf[k] = arr[j]
                j += 1
            k += 1
        while i < mid:
            buf[k] = arr[i]; i += 1; k += 1
        while j < hi:
            buf[k] = arr[j]; j += 1; k += 1
        arr[lo:hi] = buf[lo:hi]

    sys.setrecursionlimit(max(10_000, len(arr) * 2))
    sort(0, len(arr))
    return int(count)


def _tie_pairs(sorted_values) -> int:
    total = 0
    i = 0
    n = len(sorted_values)
    while i < n:
        j = i
        while j + 1 < n and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        t = j - i + 1
        total += t * (t - 1) // 2
        i = j + 1
    return int(total)


def kendall_tau_b(x, y) -> float | None:
    """Kendall's ``tau-b`` with the standard tie correction. ``None`` if flat.

    Implemented rather than imported: it is one of the two numbers the owner's
    question turns on, its known answer (an exact negative gives ``-1``) is a
    registered test, and a brute-force O(n^2) count is asserted against it on
    toy data.
    """
    xs = np.asarray(x, dtype=np.float64)
    ys = np.asarray(y, dtype=np.float64)
    n = xs.size
    if n < 2 or ys.size != n:
        return None
    perm = np.lexsort((ys, xs))
    xs, ys = xs[perm], ys[perm]
    total = n * (n - 1) // 2
    xtie = _tie_pairs(xs.tolist())
    ytie = _tie_pairs(np.sort(ys).tolist())
    # pairs tied in both coordinates
    joint = 0
    i = 0
    xl, yl = xs.tolist(), ys.tolist()
    while i < n:
        j = i
        while j + 1 < n and xl[j + 1] == xl[i] and yl[j + 1] == yl[i]:
            j += 1
        t = j - i + 1
        joint += t * (t - 1) // 2
        i = j + 1
    dis = _inversions(yl)
    con_minus_dis = total - xtie - ytie + joint - 2 * dis
    denom = (total - xtie) * (total - ytie)
    if denom <= 0:
        return None
    return float(con_minus_dis / math.sqrt(denom))


def reversed_pair_fraction(x, y) -> dict:
    """Discordant pairs over all pairs, with the tie counts beside it."""
    xs = np.asarray(x, dtype=np.float64)
    ys = np.asarray(y, dtype=np.float64)
    n = xs.size
    if n < 2:
        return {"pairs": 0, "discordant": 0, "fraction": None}
    perm = np.lexsort((ys, xs))
    dis = _inversions(ys[perm].tolist())
    total = n * (n - 1) // 2
    return {"pairs": int(total), "discordant": int(dis),
            "fraction": float(dis / total),
            "tied_in_x": _tie_pairs(np.sort(xs).tolist()),
            "tied_in_y": _tie_pairs(np.sort(ys).tolist())}


def pearson(x, y) -> float | None:
    a = np.asarray(x, dtype=np.float64)
    b = np.asarray(y, dtype=np.float64)
    if a.size < 2 or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def ols(x, y) -> dict:
    """``y = a + b x`` by least squares, with ``R^2``. No library fit."""
    a_ = np.asarray(x, dtype=np.float64)
    b_ = np.asarray(y, dtype=np.float64)
    if a_.size < 2 or a_.std() == 0:
        return {"a": None, "b": None, "r2": None, "n": int(a_.size)}
    xbar, ybar = a_.mean(), b_.mean()
    sxx = float(((a_ - xbar) ** 2).sum())
    sxy = float(((a_ - xbar) * (b_ - ybar)).sum())
    slope = sxy / sxx
    intercept = float(ybar - slope * xbar)
    resid = b_ - (intercept + slope * a_)
    sst = float(((b_ - ybar) ** 2).sum())
    r2 = None if sst == 0 else float(1.0 - float((resid ** 2).sum()) / sst)
    return {"a": intercept, "b": float(slope), "r2": r2, "n": int(a_.size)}


# ----------------------------------------------------------------- input
def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_pairs() -> tuple[list[dict], dict]:
    grid = L.D11_GRID
    trained = {(r["cutoff_ts"], r["stable_id"]): r
               for r in read_jsonl(grid / "scores_trained.jsonl")}
    reference = {(r["cutoff_ts"], r["stable_id"]): r
                 for r in read_jsonl(grid / "scores_reference.jsonl")}
    labels = {(r["cutoff_ts"], r["stable_id"]): r
              for r in read_jsonl(grid / "labels.jsonl")}
    blocks = L.split()["temporal_blocks"]
    rows = []
    for key, tr in trained.items():
        rf = reference.get(key)
        if rf is None:
            continue
        if tr.get("status") != "VALID" or rf.get("status") != "VALID":
            continue
        lab = labels.get(key)
        rows.append({
            "cutoff_ts": key[0], "stable_id": key[1],
            "tick": int(tr["tick"]),
            "block": C.block_of(key[0], blocks),
            "trained": float(tr["valence_hz"]),
            "reference": float(rf["valence_hz"]),
            "settled": bool(lab and lab.get("settled")),
            "y": bool(lab.get("positive")) if lab and lab.get("settled")
            else None,
        })
    rows.sort(key=lambda r: (r["cutoff_ts"], r["stable_id"]))
    meta = {"scores_trained": len(trained), "scores_reference": len(reference),
            "valid_in_both": len(rows),
            "digest_trained": next(iter(trained.values()))["checkpoint_digest"],
            "digest_reference": next(iter(reference.values()))["checkpoint_digest"]}
    return rows, meta


def block_of_rows(rows, key="block") -> dict:
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


def describe(rows) -> dict:
    t = [r["trained"] for r in rows]
    f = [r["reference"] for r in rows]
    return {
        "n": len(rows),
        "pearson_r": pearson(f, t),
        "spearman_rho": ST.spearman(f, t),
        "kendall_tau": kendall_tau_b(f, t),
        "ols_trained_on_reference": ols(f, t),
        "reversed_pairs": reversed_pair_fraction(f, t),
    }


def analyse() -> dict:
    rows, meta = load_pairs()
    overall = describe(rows)

    per_block = []
    for block, sub in sorted(block_of_rows(rows).items(),
                             key=lambda kv: (kv[0] is None, kv[0])):
        per_block.append({"block": block, **describe(sub)})

    # within tick: the cohort-wise tau, the quantity that matters for ranking
    taus, sizes, degenerate = [], [], 0
    for tick, sub in sorted(block_of_rows(rows, "tick").items()):
        if len(sub) < 2:
            degenerate += 1
            continue
        tau = kendall_tau_b([r["reference"] for r in sub],
                            [r["trained"] for r in sub])
        if tau is None:
            degenerate += 1
            continue
        taus.append(tau)
        sizes.append(len(sub))
    arr = np.array(taus or [0.0])
    within_tick = {
        "ticks_with_a_tau": len(taus),
        "ticks_without_one": degenerate,
        "mean_tau": float(arr.mean()) if taus else None,
        "median_tau": float(np.median(arr)) if taus else None,
        "min_tau": float(arr.min()) if taus else None,
        "max_tau": float(arr.max()) if taus else None,
        "sd_tau": float(arr.std(ddof=1)) if len(taus) > 1 else None,
        "ticks_with_tau_at_minus_one": int((arr == -1.0).sum()) if taus else 0,
        "ticks_with_a_negative_tau": int((arr < 0).sum()) if taus else 0,
        "size_weighted_mean_tau": (
            float(np.average(arr, weights=np.array(sizes)))
            if taus else None),
        "cohort_size": {"min": int(min(sizes)), "median": float(np.median(sizes)),
                        "max": int(max(sizes))} if sizes else None,
    }

    labelled = [r for r in rows if r["settled"]]
    y = [r["y"] for r in labelled]
    auc_trained = ST.auc([r["trained"] for r in labelled], y)
    auc_reference = ST.auc([r["reference"] for r in labelled], y)
    auc_neg_reference = ST.auc([-r["reference"] for r in labelled], y)
    mirror = {
        "labelled_rows": len(labelled),
        "positive": sum(1 for v in y if v), "negative": sum(1 for v in y if not v),
        "auc_trained": auc_trained,
        "auc_reference": auc_reference,
        "auc_minus_reference": auc_neg_reference,
        "one_minus_auc_reference": (None if auc_reference is None
                                    else 1.0 - auc_reference),
        "residual_of_auc_trained_from_one_minus_auc_reference": (
            None if (auc_trained is None or auc_reference is None)
            else auc_trained - (1.0 - auc_reference)),
        "residual_of_auc_trained_from_auc_minus_reference": (
            None if (auc_trained is None or auc_neg_reference is None)
            else auc_trained - auc_neg_reference),
    }
    return {
        "version": "d12-001-mirror-1",
        "inputs": {name: str(L.D11_GRID / name) for name in
                   ("scores_trained.jsonl", "scores_reference.jsonl",
                    "labels.jsonl")},
        "input_sha256": {name: L.sha256_file(L.D11_GRID / name) for name in
                         ("scores_trained.jsonl", "scores_reference.jsonl",
                          "labels.jsonl")},
        "no_brain_ran": True, "no_socket_was_opened": True,
        "meta": meta,
        "overall": overall,
        "per_block": per_block,
        "within_tick": within_tick,
        "auc": mirror,
        "wording": ("numbers. The mechanistic reading is a hypothesis that b "
                    "and tau test; it is not a finding until the owner states "
                    "it as one."),
    }


def _f(v, digits=4, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def render(payload: dict) -> str:
    o = payload["overall"]
    w = payload["within_tick"]
    a = payload["auc"]
    m = payload["meta"]
    L_ = []
    A = L_.append
    A("# The mirror diagnostic — is the trained brain the negative of the "
      "untrained one?")
    A("")
    A("Fable addendum 5, computed in step (iii) of the D12 wave **before any "
      "new run**, from two files `d11-001` already wrote. No brain ran, no "
      "socket was opened, nothing was recomputed: "
      f"`{Path(payload['inputs']['scores_trained.jsonl']).name}` "
      f"(`{payload['input_sha256']['scores_trained.jsonl'][:12]}…`) and "
      f"`{Path(payload['inputs']['scores_reference.jsonl']).name}` "
      f"(`{payload['input_sha256']['scores_reference.jsonl'][:12]}…`).")
    A("")
    A(f"**{m['valid_in_both']:,}** of {m['scores_trained']:,} grid rows are "
      f"`VALID` under both brains — TRAINED `{m['digest_trained'][:12]}…` and "
      f"REFERENCE `{m['digest_reference'][:12]}…`.")
    A("")
    A("## 1. The two valences, row by row")
    A("")
    A("| | n | Pearson r | Spearman ρ | Kendall τ | OLS a | OLS b | R² | "
      "reversed pairs |")
    A("|---|---|---|---|---|---|---|---|---|")

    def row(name, d):
        f = d["ols_trained_on_reference"]
        rp = d["reversed_pairs"]
        A(f"| {name} | {d['n']:,} | {_f(d['pearson_r'])} | "
          f"{_f(d['spearman_rho'])} | {_f(d['kendall_tau'])} | "
          f"{_f(f['a'])} | **{_f(f['b'])}** | {_f(f['r2'])} | "
          f"{_f((rp['fraction'] or 0) * 100, 2)} % |")

    row("**overall**", o)
    for entry in payload["per_block"]:
        row(f"block {entry['block']}", entry)
    A("")
    A("`b` is the slope of `trained = a + b · reference` in Hz per Hz. A brain "
      "that had become the exact negative of the untrained one would show "
      "`b = −1`, `τ = −1` and 100 % of row pairs reversed.")
    A("")
    A("## 2. Within a tick — the ranking the fly would actually act on")
    A("")
    A(f"Kendall τ between the two branches **inside each tick's cohort**, "
      f"which is the quantity that decides which candidate a round selects: "
      f"mean **{_f(w['mean_tau'])}** over {w['ticks_with_a_tau']:,} ticks "
      f"(median {_f(w['median_tau'])}, SD {_f(w['sd_tau'])}, range "
      f"[{_f(w['min_tau'])}, {_f(w['max_tau'])}]; size-weighted mean "
      f"{_f(w['size_weighted_mean_tau'])}). "
      f"**{w['ticks_with_a_negative_tau']:,}** of those ticks have a negative "
      f"τ and **{w['ticks_with_tau_at_minus_one']:,}** have τ exactly −1 — a "
      f"cohort ranked in perfectly reversed order. "
      f"{w['ticks_without_one']:,} ticks carry fewer than two comparable rows "
      f"and have no τ.")
    A("")
    A("## 3. The AUCs, beside each other")
    A("")
    A("| quantity | value |")
    A("|---|---|")
    A(f"| rows with a settled label | {a['labelled_rows']:,} "
      f"({a['positive']:,} positive / {a['negative']:,} negative) |")
    A(f"| AUC(trained) | **{_f(a['auc_trained'], 6)}** |")
    A(f"| AUC(reference) | {_f(a['auc_reference'], 6)} |")
    A(f"| AUC(−reference) | **{_f(a['auc_minus_reference'], 6)}** |")
    A(f"| 1 − AUC(reference) | {_f(a['one_minus_auc_reference'], 6)} |")
    A(f"| AUC(trained) − (1 − AUC(reference)) | "
      f"**{_f(a['residual_of_auc_trained_from_one_minus_auc_reference'], 6)}** |")
    A(f"| AUC(trained) − AUC(−reference) | "
      f"{_f(a['residual_of_auc_trained_from_auc_minus_reference'], 6)} |")
    A("")
    A(f"The two lines of this page that answer the owner's question sit in "
      f"different sections and are stated together here, as numbers: the "
      f"residual of AUC(trained) from 1 − AUC(reference) is "
      f"**{_f(a['residual_of_auc_trained_from_one_minus_auc_reference'], 6)}**, "
      f"while Kendall τ between the two rankings over the same rows is "
      f"**{_f(o['kendall_tau'])}**, the OLS slope is "
      f"**{_f(o['ols_trained_on_reference']['b'])}** and the "
      f"mean within-tick τ is **{_f(w['mean_tau'])}**. One scalar lands on the "
      f"mirror; the ordering that scalar summarises does not. Both are "
      f"reported and neither is interpreted here.")
    A("")
    A("## 4. What these numbers are, and what they are not")
    A("")
    A("They are a description of two recorded score files. The mechanistic "
      "reading — that fifteen punishments depressed the approach pathway in "
      "proportion to the prior valence, so the trained valence is a decreasing "
      "affine function of the untrained one — is a **hypothesis** that `b` and "
      "`τ` test. It is **not a finding** until the owner states it as one. "
      "Nothing here is a rate in the market, and no interval was "
      "pre-registered for any single AUC above.")
    return "\n".join(L_) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=str(L.HERE / "mirror_diagnostic.json"))
    parser.add_argument("--md", default=str(L.HERE / "mirror_diagnostic.md"))
    args = parser.parse_args(argv)
    t0 = time.time()
    payload = analyse()
    payload["elapsed_s"] = round(time.time() - t0, 1)
    L.atomic_write_json(Path(args.json), payload)
    Path(args.md).write_text(render(payload))
    o, a = payload["overall"], payload["auc"]
    print(f"n {o['n']:,}  r {o['pearson_r']:.4f}  rho {o['spearman_rho']:.4f}  "
          f"tau {o['kendall_tau']:.4f}  b {o['ols_trained_on_reference']['b']:.4f}  "
          f"R2 {o['ols_trained_on_reference']['r2']:.4f}")
    print(f"AUC(trained) {a['auc_trained']:.4f}  AUC(-reference) "
          f"{a['auc_minus_reference']:.4f}  residual "
          f"{a['residual_of_auc_trained_from_one_minus_auc_reference']:+.4f}")
    print(f"within-tick mean tau {payload['within_tick']['mean_tau']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
