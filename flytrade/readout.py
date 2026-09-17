"""
The readout policy — repeated measurement, aggregation, and the WAIT margin.

Canonical amendment D4 (``docs/SPEC.md``) and Fable addenda 2-5. This module
owns the one thing D4 changes: **how many times a candidate is presented before
the fixed decoder is applied to it, and how those measurements are combined**.

    8 neural measurements per candidate
      -> 1 aggregate candidate readout
      -> 1 final decision
      -> at most 1 execution episode
      -> 1 outcome-linked learning event.

Nothing else moves. The gain is 0.10, the window is 20 ms, the encoder input
range, the sensory populations, the MBON membership, the decoder formula, its
sign convention and its dimensionless margin coefficient 1.0 are all exactly
what ``docs/ENCODER.md`` and ``docs/DECODER.md`` already fix. What k = 8 buys
is a smaller measurement noise on the same quantity, and the price is a
baseline that has to be re-measured for the new estimator (§3 below).

## 1. Repeated measurement

One **batch** is k presentations of one candidate's stimulus under one frozen
learned state. Between replicates the runner restores the round's transient
snapshot ``S0``, so no electrical state and no eligibility crosses from one
measurement into the next; the eligibility decay therefore acts once per
*round*, not once per presentation (addendum 3), because every replicate decays
the same ``S0``.

k is fixed. A batch is never shortened because a desirable response appeared,
never lengthened because a difficult observation produced silence, and never
retried until something shows up.

## 2. The seed schedule

Addendum 2. A replicate's seed is a declared deterministic function::

    seed = sha256("<namespace>:<state digest>:<observation id>:<stable id>:<r>")
           truncated to 64 bits

* **namespace** separates the schedules of the live round, the §3 baseline and
  the §5 evaluation so that no two of them can ever draw the same stream;
* **state digest** is the learned-weight digest ``flytrade/state.py`` already
  computes for the checkpoint, so a batch taken under different learned weights
  is a different batch;
* **observation id** is a hash of the observation's *content* — bar index,
  cutoff timestamp and the normalised features — and never of the symbol;
* **stable id** is assigned at universe registration, never the candidate's
  position in a list and never Python's ``hash()``.

Two consequences are load-bearing. A batch is a pure function of (learned
state, observation, schedule), which is what makes a mid-batch restart a
deterministic **recompute** rather than a resume (addendum 7). And **k = 1 is
replicate index 0 of the same schedule**, so the k = 1 and k = 8 modes are
paired by construction rather than by a separate run.

## 3. Aggregation, and the four statuses

Amendment §2: aggregate the measurements, then apply the fixed decoder **once**.
Never majority-vote eight labels, never take the strongest replicate.

The aggregate is fed to the unmodified :class:`flytrade.decoder.ActionDecoder`
through an aggregate :class:`flytrade.runner.Presentation` built so that the
decoder's own rule order reproduces addendum 4's status rules exactly:

===============================  =========================================
aggregate ``rates``              per-neuron **mean** over the k replicates
aggregate ``kc_fraction``        **max** over the replicates
aggregate ``max_rate_hz``        **max** over the replicates
===============================  =========================================

so that

* ``INVALID_STATE`` iff **any** replicate is saturated or over-recruited —
  saturation is not hidden by averaging it with quieter trials;
* ``NO_RESPONSE`` iff **all** replicates were silent over the 45 decoder MBONs
  — a silent replicate inside an active batch contributes its zeros and is
  never discarded;
* otherwise ``VALID``, and ``WAIT`` iff ``|V_k| <= theta_k``.

A replicate that raises is a **technical failure**: it aborts the round, which
emits one ``ROUND_ABORTED`` event and no decision. It is not averaged, not
retried and not silently dropped.

The four cases the amendment insists stay apart — genuine absence of output
activity, valid activity with a near-neutral score, saturation or invalid
state, and technical execution failure — are four different things here and in
every record.

## 4. The margin

The decoder expresses WAIT in units of the measured dispersion of its own
baseline readout. Replacing one presentation by the mean of k changes that
dispersion, so a k = 8 baseline has to be measured under the same rule before
k = 8 can decide anything (amendment §3). The procedure is pre-registered in
``experiments/k8_readout/PROTOCOL.md``; the measured artifact and its
provenance are ``experiments/k8_readout/baseline_k8.json``. The coefficient
stays 1.0 and the formula stays ``V = mean(approach) - mean(avoid) - BASELINE``.

The k = 1 constants in ``flytrade/decoder.py`` are untouched and remain the
constants of the k = 1 regression mode.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import decoder as D
from . import runner as R
from . import state as S

VERSION = "flytrade-readout-1"

#: the fixed number of presentations per candidate evaluation. D4 resolved as
#: option (a): eight, never increased, never reduced, never retried.
K = 8

#: seed-schedule namespaces. Disjoint by construction: a seed drawn under one
#: of these can never equal a seed drawn under another for the same tuple, and
#: none of them can collide with the small integer schedules Phase One used,
#: which are all below 2**32 while these are 64-bit digests.
ROUND_NAMESPACE = "flytrade-k8-round-1"
BASELINE_NAMESPACE = "flytrade-k8-baseline-1"
EVAL_NAMESPACE = "flytrade-k8-eval-1"
BENCH_NAMESPACE = "flytrade-k8-bench-1"

#: D6 §6, Fable addendum 5. The **paired** schedule of the frozen evaluation.
#: It is a namespace of its own and it is versioned, because the comparison it
#: keys is versioned: ``comparison_v1``.
COMPARISON_NAMESPACE = "comparison_v1"

#: bits kept from the SHA-256 of the seed tuple (Fable addendum 2)
SEED_BITS = 64
_SEED_MASK = (1 << SEED_BITS) - 1


# ------------------------------------------------------------ the schedule

def replicate_seed(namespace: str, state_digest: str, observation_id: str,
                   stable_id: int, r: int) -> int:
    """The declared per-replicate seed. See §2 of the module docstring."""
    h = hashlib.sha256(
        f"{namespace}:{state_digest}:{observation_id}:{int(stable_id)}:{int(r)}"
        .encode()).digest()
    return int.from_bytes(h[:SEED_BITS // 8], "big") & _SEED_MASK


def comparison_seed(observation_id_: str, stable_id: int, r: int) -> int:
    """The ``comparison_v1`` replicate seed. **Not** keyed to the weights.

    D6 amendment §6: "The comparison random schedule must not change merely
    because the learned weights differ. A seed derived from the weight digest
    would change the stimulus realization between branches."

    So the learned-state digest — which is in every other schedule in this
    module, deliberately — is deliberately *absent* here. The tuple is
    (observation id, instrument stable id, replicate index) and nothing else,
    which is exactly what makes the learned branch and the untrained reference
    branch draw the **same Poisson stream for the same observation**. A
    difference between the two branches is then a difference in weights, not
    in noise.

    The D4 schedule and its artifacts are untouched and remain the historical
    regression evidence; this is a second, separately named schedule, used only
    inside the frozen evaluation.
    """
    h = hashlib.sha256(
        f"{COMPARISON_NAMESPACE}:{observation_id_}:{int(stable_id)}:{int(r)}"
        .encode()).digest()
    return int.from_bytes(h[:SEED_BITS // 8], "big") & _SEED_MASK


def observation_id(obs) -> str:
    """Content hash of one market observation. Never its symbol.

    Two instruments whose observations are identical in content still get
    different seeds, because the stable id enters the seed tuple separately.
    What may never enter is the spelling of a ticker or its position in a list.
    """
    h = hashlib.sha256()
    h.update(f"{int(obs.bar_index)}:{int(obs.cutoff_ts)}:"
             f"{obs.status.value}".encode())
    h.update(np.ascontiguousarray(obs.normalized, dtype=np.float64).tobytes())
    return h.hexdigest()


def features_id(normalized, *, label: str = "") -> str:
    """Content hash of a bare normalised feature vector.

    The §3 baseline and the §5 nominal patterns are not market observations;
    they are feature vectors placed at declared points of the input range, and
    this is their observation id.
    """
    h = hashlib.sha256()
    h.update(label.encode())
    h.update(np.ascontiguousarray(normalized, dtype=np.float64).tobytes())
    return h.hexdigest()


def state_digest(mb, graph_sha256: str = "") -> str:
    """Digest of the learned state a batch was taken under."""
    return S.learned_state_digest(mb.gain, mb.pos, graph_sha256)


# ------------------------------------------------------------- the batch

class TechnicalFailure(RuntimeError):
    """A replicate raised. The round aborts; nothing is averaged or retried."""


@dataclass(frozen=True)
class Replicate:
    """One presentation inside a batch, with everything §2 asks be stored."""

    index: int
    seed: int
    presentation: R.Presentation
    trace: R.StoredTrace
    #: per-replicate decode under the **k = 1** constants — recorded, never
    #: voted on. This is exactly what the k = 1 mode would have produced.
    action: str = ""
    status: str = ""
    score_hz: float = 0.0

    @property
    def silent(self) -> bool:
        return all(float(v.sum()) == 0.0
                   for v in self.presentation.rates.values())

    def as_dict(self) -> dict:
        return {"index": self.index, "seed": self.seed,
                "action": self.action, "status": self.status,
                "score_hz": round(float(self.score_hz), 6),
                "silent": self.silent,
                "eligibility": self.trace.as_dict() if self.trace else None,
                **self.presentation.as_dict()}


@dataclass(frozen=True)
class Batch:
    """k presentations of one candidate, and the one aggregate they decode to."""

    stable_id: int
    episode_id: int
    k: int
    namespace: str
    state_digest: str
    observation_id: str
    replicates: tuple[Replicate, ...]
    aggregate: R.Presentation
    traces: R.StoredTraceSet
    compute_s: float = 0.0

    @property
    def silent_replicates(self) -> int:
        return sum(1 for r in self.replicates if r.silent)

    @property
    def invalid_replicates(self) -> int:
        return sum(1 for r in self.replicates
                   if r.status == D.ReadoutStatus.INVALID_STATE.value)

    def as_dict(self) -> dict:
        return {
            "readout_version": VERSION, "k": self.k,
            "namespace": self.namespace,
            "state_digest": self.state_digest,
            "observation_id": self.observation_id,
            "stable_id": self.stable_id, "episode_id": self.episode_id,
            "silent_replicates": self.silent_replicates,
            "invalid_replicates": self.invalid_replicates,
            "compute_s": round(float(self.compute_s), 6),
            "aggregate": self.aggregate.as_dict(),
            "replicates": [r.as_dict() for r in self.replicates],
        }


def aggregate_presentation(stimulus, replicates, *, episode_id: int,
                           k: int) -> R.Presentation:
    """Build the one presentation the fixed decoder is applied to.

    Rates are the per-neuron mean over the replicates; ``kc_fraction`` and
    ``max_rate_hz`` are **maxima**, so that the decoder's unchanged rule order
    produces addendum 4's aggregate status rules. See §3 above.
    """
    names = list(replicates[0].presentation.rates)
    rates = {n: np.mean(np.stack([r.presentation.rates[n]
                                  for r in replicates]), axis=0)
             for n in names}
    kc_f = [r.presentation.kc_fraction for r in replicates]
    return R.Presentation(
        symbol=stimulus.symbol, stable_id=stimulus.stable_id,
        episode_id=int(episode_id), seed=replicates[0].seed,
        steps=replicates[0].presentation.steps, rates=rates,
        kc_fraction=float(max(kc_f)),
        kc_active=int(round(float(np.mean([r.presentation.kc_active
                                           for r in replicates])))),
        total_hz=float(np.mean([r.presentation.total_hz for r in replicates])),
        max_rate_hz=float(max(r.presentation.max_rate_hz for r in replicates)),
        n_eligible=int(replicates[0].presentation.n_eligible),
        k=int(k),
        seeds=tuple(int(r.seed) for r in replicates),
        kc_fraction_mean=float(np.mean(kc_f)),
        silent_replicates=sum(1 for r in replicates if r.silent),
        invalid_replicates=sum(
            1 for r in replicates
            if r.status == D.ReadoutStatus.INVALID_STATE.value),
    )


# ----------------------------------------------------------- the margin

class DegenerateBaseline(RuntimeError):
    """The baseline distribution has no dispersion to normalise by.

    Amendment §3: "Handle zero or degenerate baseline dispersion explicitly. Do
    not hide it with an arbitrary divisor." There is no substitute divisor here
    and no epsilon. If the k = 8 aggregate is identical in every batch at the
    neutral reference then the margin is undefined, and the wave stops and
    reports it (Fable addendum 5).
    """


#: what the k = 8 baseline normalises, stated once so it cannot be quietly
#: swapped for a standard error later
DISTRIBUTION = ("the k-presentation aggregate raw valence V_raw = "
                "mean(approach) - mean(avoid) at the neutral reference, one "
                "sample per BATCH, sample standard deviation with ddof=1 - "
                "never the standard error of that mean")


@dataclass(frozen=True)
class Baseline:
    """A measured baseline offset and WAIT margin for one value of k.

    The decoder formula and the dimensionless margin coefficient are unchanged:
    ``V = V_raw - baseline_hz`` and ``theta = theta_sd x sd_hz`` with
    ``theta_sd = 1.0``. What k changes is the dispersion of ``V_raw``, and
    therefore the size of the margin in Hz — nothing else.
    """

    k: int
    baseline_hz: float
    sd_hz: float
    n_batches: int
    theta_sd: float = D.THETA_SD
    namespace: str = BASELINE_NAMESPACE
    distribution: str = DISTRIBUTION
    stimulus: str = "neutral_reference"
    graph_sha256: str = ""
    state_digest: str = ""
    readout_version: str = VERSION
    decoder_version: str = D.VERSION
    commit: str = ""
    measured_at: float = 0.0
    samples: tuple = field(default=(), repr=False)

    @property
    def theta_hz(self) -> float:
        return float(self.theta_sd) * float(self.sd_hz)

    @classmethod
    def from_samples(cls, samples, *, k: int, **kw) -> "Baseline":
        """Mean and sample SD of the per-batch aggregate. Never a standard error."""
        x = np.asarray(list(samples), dtype=np.float64)
        if len(x) < 2:
            raise DegenerateBaseline(
                f"a dispersion needs at least two batches, got {len(x)}")
        if not np.all(np.isfinite(x)):
            raise DegenerateBaseline("the baseline samples are not all finite")
        sd = float(x.std(ddof=1))
        # identical samples can still leave a ~1e-16 residue behind the mean's
        # own rounding, so degeneracy is tested on the samples, not on the SD
        if sd <= 0.0 or bool(np.all(x == x[0])):
            raise DegenerateBaseline(
                f"the k = {k} aggregate is identical in all {len(x)} baseline "
                f"batches, so the WAIT margin has no unit. No substitute "
                f"divisor is applied; this is reported, not patched.")
        return cls(k=int(k), baseline_hz=float(x.mean()), sd_hz=sd,
                   n_batches=int(len(x)),
                   samples=tuple(float(v) for v in x), **kw)

    def decoder(self) -> D.ActionDecoder:
        """The fixed decoder carrying this baseline. Same formula, same sign."""
        return D.ActionDecoder(baseline_hz=self.baseline_hz,
                               theta_hz=self.theta_hz)

    def as_dict(self) -> dict:
        return {"k": self.k, "baseline_hz": self.baseline_hz,
                "sd_hz": self.sd_hz, "theta_sd": self.theta_sd,
                "theta_hz": self.theta_hz, "n_batches": self.n_batches,
                "namespace": self.namespace, "distribution": self.distribution,
                "stimulus": self.stimulus, "graph_sha256": self.graph_sha256,
                "state_digest": self.state_digest,
                "readout_version": self.readout_version,
                "decoder_version": self.decoder_version,
                "commit": self.commit, "measured_at": self.measured_at,
                "samples": list(self.samples)}

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2) + "\n")
        return path


def load_baseline(path, *, k: int | None = None,
                  graph_sha256: str | None = None) -> Baseline:
    """Read a baseline artifact, validating what it was measured against."""
    path = Path(path)
    d = json.loads(path.read_text())
    b = Baseline(k=int(d["k"]), baseline_hz=float(d["baseline_hz"]),
                 sd_hz=float(d["sd_hz"]), n_batches=int(d["n_batches"]),
                 theta_sd=float(d["theta_sd"]), namespace=d["namespace"],
                 distribution=d["distribution"], stimulus=d["stimulus"],
                 graph_sha256=d["graph_sha256"],
                 state_digest=d["state_digest"],
                 readout_version=d["readout_version"],
                 decoder_version=d["decoder_version"], commit=d["commit"],
                 measured_at=float(d["measured_at"]),
                 samples=tuple(d.get("samples", ())))
    if b.sd_hz == 0.0:
        raise DegenerateBaseline(f"{path} carries zero dispersion")
    if k is not None and b.k != int(k):
        raise ValueError(f"{path} is a k = {b.k} baseline, k = {k} was asked "
                         "for; a margin measured for one k is not a margin "
                         "for another")
    if graph_sha256 is not None and b.graph_sha256 != graph_sha256:
        raise ValueError(f"{path} was measured against graph "
                         f"{b.graph_sha256[:12]}, the graph in use is "
                         f"{graph_sha256[:12]}")
    return b


# ------------------------------------- the measured k = 8 constants

#: Where the two numbers below come from. The file is the artifact; these are
#: its values, carried in code the way ``decoder.py`` carries the k = 1
#: constants measured by ``encoder_range.json``.
BASELINE_ARTIFACT = "experiments/k8_readout/baseline_k8.json"

#: Mean of the k = 8 aggregate ``V_raw`` at the neutral reference over the
#: N = 64 batches of the ``flytrade-k8-baseline-1`` schedule, unlearned
#: weights, gain 0.10, 20 ms window, graph ``8feb08a0d2a8``. Measured by
#: ``experiments/k8_readout/baseline.py`` under the procedure pre-registered in
#: ``PROTOCOL.md`` §3 at commit ``4b8e082``, which contains that file alone.
BASELINE_HZ_K8 = -0.844389816810345

#: Sample SD (ddof = 1) of the same 64 **batch** samples. Not a standard error
#: and not a within-batch dispersion. This is the unit the k = 8 WAIT margin is
#: in, exactly as ``BASELINE_SD_HZ`` is the unit of the k = 1 margin.
BASELINE_SD_HZ_K8 = 0.9117185769796697

#: The k = 8 WAIT margin. The dimensionless coefficient is
#: ``decoder.THETA_SD`` = 1.0, unchanged: only the Hz it multiplies changed.
THETA_HZ_K8 = D.THETA_SD * BASELINE_SD_HZ_K8


def baseline_k8() -> Baseline:
    """The measured k = 8 baseline, as a :class:`Baseline`."""
    return Baseline(k=K, baseline_hz=BASELINE_HZ_K8, sd_hz=BASELINE_SD_HZ_K8,
                    n_batches=64, namespace=BASELINE_NAMESPACE)


def decoder_k8() -> D.ActionDecoder:
    """The fixed decoder carrying the k = 8 baseline and margin."""
    return D.ActionDecoder(baseline_hz=BASELINE_HZ_K8, theta_hz=THETA_HZ_K8)


def policy_k8(**kw) -> "ReadoutPolicy":
    """The wave's readout policy: k = 8, round namespace, k = 8 margin."""
    kw.setdefault("decoder", decoder_k8())
    return ReadoutPolicy(k=K, **kw)


def policy_comparison(**kw) -> "ComparisonReadoutPolicy":
    """The frozen evaluation's readout policy: k = 8, ``comparison_v1``."""
    kw.setdefault("decoder", decoder_k8())
    kw.setdefault("namespace", COMPARISON_NAMESPACE)
    return ComparisonReadoutPolicy(k=K, **kw)


# ------------------------------------------------------------ the policy

class ReadoutPolicy:
    """Versioned: how many presentations, which seeds, and how they combine.

    ``decoder`` is the decoder applied **once** to the aggregate — at k = 8 it
    carries the k = 8 baseline and margin. ``decoder_k1`` is applied to each
    replicate for the record only; its output is never voted on and never
    selects anything.
    """

    version = VERSION

    def __init__(self, *, k: int = K, namespace: str = ROUND_NAMESPACE,
                 decoder: D.ActionDecoder | None = None,
                 decoder_k1: D.ActionDecoder | None = None):
        if int(k) < 1:
            raise ValueError("k must be at least 1")
        self.k = int(k)
        self.namespace = str(namespace)
        self.decoder_k1 = decoder_k1 or D.ActionDecoder()
        self.decoder = decoder or self.decoder_k1

    @classmethod
    def from_baseline(cls, baseline: Baseline, **kw) -> "ReadoutPolicy":
        """A policy at the baseline's own k, decoding with its own margin."""
        kw.setdefault("k", baseline.k)
        kw.setdefault("decoder", baseline.decoder())
        return cls(**kw)

    @classmethod
    def k1(cls, **kw) -> "ReadoutPolicy":
        """The explicit regression/comparison mode: replicate index 0 only.

        Not a fallback. Nothing selects it automatically; a caller asks for it
        by name, and it draws replicate 0 of the very same schedule k = 8 uses.
        """
        kw.setdefault("k", 1)
        return cls(**kw)

    # -- seeds ------------------------------------------------------------

    def seeds(self, state_dig: str, obs_id: str, stable_id: int) -> list[int]:
        return [replicate_seed(self.namespace, state_dig, obs_id, stable_id, r)
                for r in range(self.k)]

    # -- one batch --------------------------------------------------------

    def measure(self, run, stimulus, *, episode_id: int, state_dig: str,
                obs_id: str, snapshot=None) -> Batch:
        """Present ``stimulus`` k times from equivalent transient states.

        The round's snapshot is restored before **every** replicate, including
        the first, so that no electrical state and no eligibility crosses from
        one measurement into the next and the eligibility decay acts once per
        round rather than once per presentation.
        """
        stable_id = int(stimulus.stable_id)
        s0 = run.snapshot() if snapshot is None else snapshot
        seeds = self.seeds(state_dig, obs_id, stable_id)
        reps: list[Replicate] = []
        t0 = time.perf_counter()
        for r, seed in enumerate(seeds):
            run.restore(s0)
            run.clear_episode(episode_id)
            try:
                pres = run.present(stimulus, seed=seed, episode_id=episode_id)
            except Exception as exc:                 # technical failure
                raise TechnicalFailure(
                    f"replicate {r} of stable id {stable_id} raised: "
                    f"{type(exc).__name__}: {exc}") from exc
            d = self.decoder_k1.decode(pres)
            reps.append(Replicate(index=r, seed=int(seed), presentation=pres,
                                  trace=run.capture_trace(episode_id),
                                  action=d.action.value, status=d.status.value,
                                  score_hz=float(d.valence_hz)))
        compute_s = time.perf_counter() - t0
        run.restore(s0)
        return Batch(
            stable_id=stable_id, episode_id=int(episode_id), k=self.k,
            namespace=self.namespace, state_digest=state_dig,
            observation_id=obs_id, replicates=tuple(reps),
            aggregate=aggregate_presentation(stimulus, reps,
                                             episode_id=episode_id, k=self.k),
            traces=R.StoredTraceSet.of(episode_id, [r.trace for r in reps]),
            compute_s=compute_s)

    # -- decoding ---------------------------------------------------------

    def decode(self, batch: Batch) -> D.Decision:
        """The fixed decoder, applied **once**, to the aggregate."""
        return self.decoder.decode(batch.aggregate)

    def score(self, evaluation) -> float | None:
        """Selection score: the aggregate's centred valence, or None."""
        if evaluation.presentation is None:
            return None
        d = self.decoder.decode(evaluation.presentation)
        return d.valence_hz if d.status is D.ReadoutStatus.VALID else None

    def as_dict(self) -> dict:
        return {"version": self.version, "k": self.k,
                "namespace": self.namespace, "seed_bits": SEED_BITS,
                "seed_rule": "sha256(namespace:state_digest:observation_id:"
                             "stable_id:replicate_index)[:8]",
                "aggregation": "mean of per-neuron rates, decoder applied once",
                "kc_fraction": "max over replicates",
                "max_rate_hz": "max over replicates",
                "decoder": self.decoder.as_dict(),
                "decoder_per_replicate": self.decoder_k1.as_dict()}


class ComparisonReadoutPolicy(ReadoutPolicy):
    """``ReadoutPolicy`` with the paired ``comparison_v1`` seed schedule.

    Everything else — k, the aggregation, the decoder and its margin, the
    status rules, the per-replicate record — is the same object the learning
    partition uses. Only :meth:`seeds` changes, and it changes in exactly one
    way: the learned-state digest is not in the tuple.

    The digest is still *recorded* on every batch, so a reader can see that the
    two branches ran under different weights while drawing identical seeds.
    """

    def seeds(self, state_dig: str, obs_id: str, stable_id: int) -> list[int]:
        return [comparison_seed(obs_id, stable_id, r) for r in range(self.k)]

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update({
            "namespace": COMPARISON_NAMESPACE,
            "seed_rule": "sha256(comparison_v1:observation_id:stable_id:"
                         "replicate_index)[:8]",
            "keyed_to_learned_state": False,
            "why": "amendment section 6: the stimulus realisation must not "
                   "change because the weights differ",
        })
        return d
