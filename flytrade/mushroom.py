"""
Dopamine-gated depression of KC->MBON synapses — our corrected implementation.

This is the two-part fix ``docs/UPSTREAM_NOTES.md`` §2 specifies. Nothing in
``upstream/`` is touched; the upstream defect and its strict xfails stay
exactly where they are.

Part 1 — a dopaminergic connectivity source the sign rule does not erase.
    ``build_graph.py`` gives dopamine sign 0.0 and then drops zero-valued
    edges, so on the shipped ``graph.npz`` every DAN->MBON edge is gone.
    We read the compartment assignment out of ``graph_mod.npz`` instead: the
    unsigned dopaminergic synapse counts built by ``flytrade/graph.py`` from
    the anatomy, before signing. Dopamine is never turned into fast
    excitation: the modulatory matrix is only ever read as "which compartment
    does this DAN address, and with how many synapses".

Part 2 — the orientation.
    ``mushroom.py:67`` computes ``|W[pam][:, mbon].sum(axis=0)|``. Under the
    [post, pre] convention of ``build_graph.py:97-98`` that selects PAM as
    POSTsynaptic and MBON as PREsynaptic: it is MBON->PAM feedback. The
    documented read is ``D[mbon][:, pam].sum(axis=1)`` — for each MBON, the
    dopaminergic synapses it RECEIVES from PAM.

Sign of the rule (unchanged from upstream, and it was already right):
    dopamine paired with recent Kenyon-cell activity DEPRESSES that KC->MBON
    synapse, with a floor and a slow drift back toward baseline. There is no
    potentiation. Hige, Aso, Modi, Rubin & Turner 2015 (Neuron 88:985);
    Cohn, Morantte & Ruta 2015 (Cell 163:1742); Aso & Rubin 2016 (eLife
    5:e16135).

Naming: upstream's ``reward_side`` is the set of MBONs a PAM neuron
innervates. We call it ``pam_side`` and never ``reward_side``, because the
name should describe the anatomy (which DAN writes there), not a claim about
what the MBON drives. ``valence=+1`` addresses ``pam_side``, ``-1`` addresses
``ppl1_side``, which is the same mapping upstream uses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

VERSION = "flytrade-mb-1"

#: a synapse is eligible while its trace is above this
TRACE_EPS = 0.05


@dataclass
class Compartments:
    """The DAN->MBON compartment assignment, and how it was reached."""
    mbon: np.ndarray            # neuron indices of every MBON considered
    pam_in: np.ndarray          # dopaminergic synapses received from PAM
    ppl1_in: np.ndarray         # ... from PPL1
    pam_side: np.ndarray        # MBONs where pam_in  > ppl1_in
    ppl1_side: np.ndarray       # MBONs where ppl1_in > pam_in
    unclassified: np.ndarray    # MBONs with no dopaminergic input, or a tie
    ambiguous: np.ndarray       # classified, but on thin or near-tied evidence
    side: np.ndarray = field(repr=False, default=None)  # per-neuron +1/-1/0

    def summary(self) -> dict:
        return {
            "mbons": int(len(self.mbon)),
            "pam_side": int(len(self.pam_side)),
            "ppl1_side": int(len(self.ppl1_side)),
            "unclassified": int(len(self.unclassified)),
            "ambiguous": int(len(self.ambiguous)),
            "pam_synapses": float(self.pam_in.sum()),
            "ppl1_synapses": float(self.ppl1_in.sum()),
        }


def classify_compartments(mod, n, mbon_idx, pam_idx, ppl1_idx, *,
                          min_evidence: int = 3,
                          ambiguity_ratio: float = 2.0) -> Compartments:
    """Assign each MBON to the PAM- or PPL1-innervated compartment.

    ``mod`` is a :class:`flytrade.graph.ModulatoryGraph`. The read is
    ``D[mbon][:, dan].sum(axis=1)`` — post-by-pre, one number per MBON,
    counting synapses RECEIVED.

    An MBON receiving no dopaminergic input from either population, or exactly
    as much from both, is left **unclassified** rather than pushed to a side.
    Upstream's strict ``>`` comparison silently sent every 0-vs-0 MBON to
    neither side and never said so.

    ``ambiguous`` marks MBONs that *are* classified but whose evidence is thin:
    fewer than ``min_evidence`` synapses on the winning side, or a
    winner/loser ratio below ``ambiguity_ratio``. They keep their side — the
    rule is the observed connectivity — but nothing downstream may present
    them as a settled compartment assignment. Recording the ambiguity is
    required by the canonical amendment §3.
    """
    mbon_idx = np.asarray(mbon_idx, dtype=np.int64)
    pam_in = mod.input_weight(mbon_idx, pam_idx)
    ppl1_in = mod.input_weight(mbon_idx, ppl1_idx)

    is_pam = pam_in > ppl1_in
    is_ppl = ppl1_in > pam_in
    none = (pam_in == 0) & (ppl1_in == 0)
    tie = (~is_pam) & (~is_ppl) & (~none)

    win = np.maximum(pam_in, ppl1_in)
    lose = np.minimum(pam_in, ppl1_in)
    thin = win < min_evidence
    near = lose > 0
    near &= (win / np.maximum(lose, 1e-12)) < ambiguity_ratio
    amb = (is_pam | is_ppl) & (thin | near)

    side = np.zeros(n, dtype=np.int8)
    side[mbon_idx[is_pam]] = 1
    side[mbon_idx[is_ppl]] = -1
    return Compartments(
        mbon=mbon_idx, pam_in=pam_in, ppl1_in=ppl1_in,
        pam_side=mbon_idx[is_pam], ppl1_side=mbon_idx[is_ppl],
        unclassified=mbon_idx[none | tie], ambiguous=mbon_idx[amb], side=side,
    )


def kc_to_mbon_synapses(fb, kc_idx, mbon_idx):
    """Positions in ``fb.wdata`` of every KC->MBON synapse.

    ``fb.indptr``/``fb.indices`` are CSC: column ``k`` holds the postsynaptic
    targets of presynaptic ``k``. Walking the KC columns and keeping MBON
    targets therefore selects presynaptic KC, postsynaptic MBON — the correct
    orientation, and the one upstream already had right.

    Returns ``(pos, pre, post)``.
    """
    kc_idx = np.asarray(kc_idx, dtype=np.int64)
    is_mbon = np.zeros(fb.n, dtype=bool)
    is_mbon[np.asarray(mbon_idx, dtype=np.int64)] = True

    starts = fb.indptr[kc_idx]
    ends = fb.indptr[kc_idx + 1]
    cnt = ends - starts
    tot = int(cnt.sum())
    if tot == 0:
        z = np.array([], dtype=np.int64)
        return z, z.copy(), z.copy()
    # ragged gather of all outgoing synapse slots of the KCs
    off = np.repeat(starts - np.concatenate(([0], np.cumsum(cnt)[:-1])), cnt)
    slots = off + np.arange(tot)
    tgt = fb.indices[slots]
    pre = np.repeat(kc_idx, cnt)
    hit = is_mbon[tgt]
    return (slots[hit].astype(np.int64),
            pre[hit].astype(np.int64),
            tgt[hit].astype(np.int64))


class MushroomBody:
    """KC->MBON plasticity with the compartment read taken from the anatomy.

    Parameters
    ----------
    fb : flysim.FlyBrain
    mod : flytrade.graph.ModulatoryGraph
    lr, floor, recover : same meaning as upstream
    trace_decay : per **decision cycle**, not per simulation step. See
        ``flytrade/state.py`` for the conversion from a time constant; nothing
        here assumes a frontend call rate.
    """

    version = VERSION

    def __init__(self, fb, mod, kc_idx, mbon_idx, pam_idx, ppl1_idx, *,
                 lr=0.06, floor=0.25, recover=0.0008, trace_decay=0.55):
        self.fb = fb
        self.lr = float(lr)
        self.floor = float(floor)
        self.recover = float(recover)
        self.trace_decay = float(trace_decay)

        self.kc = np.asarray(kc_idx, dtype=np.int64)
        self.compartments = classify_compartments(
            mod, fb.n, mbon_idx, pam_idx, ppl1_idx)
        self.mbon = self.compartments.mbon

        self.pos, self.pre, self.post = kc_to_mbon_synapses(
            fb, self.kc, self.mbon)
        self.side = (self.compartments.side[self.post] if len(self.post)
                     else np.array([], dtype=np.int8))
        self.base = (fb.wdata[self.pos].copy() if len(self.pos)
                     else np.array([], dtype=np.float32))
        self.gain = np.ones(len(self.pos), dtype=np.float32)
        self.trace = np.zeros(len(self.pos), dtype=np.float32)

        # eligibility is scoped to an episode: a reward for episode k may only
        # depress synapses whose trace was laid down during episode k.
        self.trace_episode = np.full(len(self.pos), -1, dtype=np.int64)
        self.episode = 0
        self.events = {"reward": 0, "punish": 0, "rejected_episode": 0}

    # -- properties -------------------------------------------------------
    @property
    def pam_side(self):
        return self.compartments.pam_side

    @property
    def ppl1_side(self):
        return self.compartments.ppl1_side

    # -- the loop ---------------------------------------------------------
    def begin_episode(self, episode_id: int) -> None:
        """Start a new episode. Traces from earlier episodes stop being
        eligible; they are not silently carried into the next reward."""
        self.episode = int(episode_id)

    def observe(self, fired) -> int:
        """Note which Kenyon cells fired in the window just simulated.

        One call = one decision cycle of trace decay.
        """
        if not len(self.pos):
            return 0
        self.trace *= self.trace_decay
        if fired is None or not len(fired):
            return 0
        active = np.zeros(self.fb.n, dtype=bool)
        active[np.asarray(fired, dtype=np.int64)] = True
        sel = active[self.pre]
        self.trace[sel] = 1.0
        self.trace_episode[sel] = self.episode
        return int(sel.sum())

    def dopamine(self, valence: int, amount: float = 1.0,
                 episode_id: int | None = None) -> int:
        """Deliver a dopamine event to one compartment.

        ``valence`` +1 addresses the PAM-innervated compartment, -1 the
        PPL1-innervated one. Only synapses whose Kenyon cell was recently
        active AND whose trace belongs to ``episode_id`` are depressed.

        Returns the number of synapses depressed.
        """
        if not len(self.pos):
            return 0
        ep = self.episode if episode_id is None else int(episode_id)
        want = 1 if valence > 0 else -1
        eligible = (self.trace > TRACE_EPS)
        in_episode = self.trace_episode == ep
        stale = int((eligible & ~in_episode).sum())
        if stale:
            self.events["rejected_episode"] += stale
        hit = (self.side == want) & eligible & in_episode
        if not hit.any():
            return 0
        self.gain[hit] *= (1.0 - self.lr * amount * self.trace[hit])
        np.clip(self.gain, self.floor, 1.0, out=self.gain)
        self.events["reward" if want > 0 else "punish"] += 1
        return int(hit.sum())

    def proposed_gain_delta(self, valence: int, amount: float, trace, *,
                            gain=None):
        """The gain change one dopamine event **would** make, without making it.

        The same rule :meth:`dopamine` applies — same compartment selection,
        same eligibility threshold, same learning rate, same floor — computed
        against ``gain`` (the caller's pre-update state) and returned rather
        than written. It is how D4 §4 averages k proposed deltas that were all
        computed from the same pre-update state, instead of applying k
        sequential full-strength rewards.

        ``trace`` is a dense eligibility vector over the plastic synapses. The
        floor is applied **per replicate, before averaging**; that is a
        declared modelling convention (Fable addendum 6) and not a property of
        the biology.

        Returns ``(delta, n_hit)``.
        """
        g0 = np.asarray(self.gain if gain is None else gain, dtype=np.float64)
        t = np.asarray(trace, dtype=np.float64)
        if len(g0) != len(self.gain) or len(t) != len(self.gain):
            raise ValueError("gain and trace must span the plastic synapses")
        want = 1 if valence > 0 else -1
        hit = (self.side == want) & (t > TRACE_EPS)
        g = g0.copy()
        if hit.any():
            g[hit] = g0[hit] * (1.0 - self.lr * float(amount) * t[hit])
            np.clip(g, self.floor, 1.0, out=g)
        return g - g0, int(hit.sum())

    def forget(self) -> None:
        """Drift every gain back toward 1.0. One call = one decision cycle."""
        if len(self.gain):
            self.gain += (1.0 - self.gain) * self.recover

    def apply(self) -> None:
        """Write the learned gains into the weights the simulation reads."""
        if len(self.pos):
            self.fb.wdata[self.pos] = self.base * self.gain

    def reset_electrical(self) -> None:
        """No-op marker: the simulation holds no state between runs.

        ``flysim.FlyBrain.run`` re-initialises every membrane potential, so
        there is nothing electrical to clear. Kept so the three state layers
        (electrical / eligibility / learned weights) each have a named entry
        point; see ``flytrade/state.py``.
        """
        return None

    # -- reporting --------------------------------------------------------
    def stats(self) -> dict:
        if not len(self.gain):
            return {"synapses": 0, **self.compartments.summary()}
        return {
            "synapses": int(len(self.gain)),
            "pam_side_synapses": int((self.side == 1).sum()),
            "ppl1_side_synapses": int((self.side == -1).sum()),
            "unclassified_synapses": int((self.side == 0).sum()),
            "depressed": int((self.gain < 0.995).sum()),
            "mean_gain": float(self.gain.mean()),
            "min_gain": float(self.gain.min()),
            **self.events,
            **self.compartments.summary(),
        }
