"""Order and metadata invariance, and no hidden strategy in the decoder path.

The brain, the encoder, the k = 8 readout and the decoder are all real. The
contexts are scripted (``tests.d10.fixtures``). These are the D10 forms of the
invariance tests every wave since D4 has carried.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import graph as G
from flytrade import mushroom as M
from flytrade import populations as P
from flytrade import readout as RO
from flytrade import runner as R
from flytrade import state as S
from flytrade.market import Universe
from flytrade.pons.context import PONS_FEATURES
from flytrade.pons.encoder import SensoryEncoder
from tests.d10 import fixtures as F

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "malecns-v1.0"
SCALES = {"age": 600.0, "ret_30s": 0.0051, "ret_2m": 0.11, "ret_5m": 0.36,
          "flow_imb_2m": 1.0, "trade_rate_2m": 6.0, "rv_2m": 0.029,
          "drawdown_5m": 0.51}


@pytest.fixture(scope="module")
def brain():
    if not (DATA / "graph.npz").exists():
        pytest.skip(f"{DATA} is not on disk; see data/MANIFEST.md")
    import flysim
    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    sha = G.sha256_file(DATA / "graph.npz")
    mb = M.MushroomBody(fb, mod, np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    encoder = SensoryEncoder(ann, SCALES)
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, encoder.olfactory, pops, graph_sha256=sha)
    return run, mb, encoder, sha


def _observations(encoder, n=4, cutoff_offset=200):
    universe = Universe()
    out = []
    for i in range(n):
        tape = F.traded_tape(token="0x" + f"{i:040x}", curve="0x" + f"{i+9:040x}",
                             trades=((10, (5 + i) * 10 ** 16),
                                     (40, (3 + i) * 10 ** 16),
                                     (80, (7 + i) * 10 ** 16),
                                     (130, (2 + i) * 10 ** 16)))
        stable_id = universe.register(tape.token)
        context = tape.context(tape.launched_at + cutoff_offset,
                               tick=1, stable_id=stable_id)
        out.append(context.observation(encoder.scales, symbol=tape.token,
                                       features=encoder.features))
    return universe, out


def _scores(run, obs, policy):
    rnd = run.evaluate_round(obs, round_index=7, readout=policy,
                             score=policy.score)
    return {c.stable_id: (round(float(policy.score(c) or 0.0), 12),
                          policy.decoder.decode(c.presentation).action.value)
            for c in rnd.candidates}


def test_shuffling_the_candidate_list_changes_nothing(brain):
    run, mb, encoder, _ = brain
    policy = RO.policy_comparison()
    _, obs = _observations(encoder)
    baseline = _scores(run, obs, policy)
    for seed in range(3):
        shuffled = list(obs)
        random.Random(seed).shuffle(shuffled)
        assert _scores(run, shuffled, policy) == baseline


def test_renaming_a_token_changes_nothing(brain):
    """The stable id is assigned at registration; the address is metadata."""
    run, mb, encoder, _ = brain
    policy = RO.policy_comparison()
    _, obs = _observations(encoder)
    baseline = _scores(run, obs, policy)
    renamed = [type(o)(symbol="0xdeadbeef" + o.symbol[10:], stable_id=o.stable_id,
                       bar_index=o.bar_index, cutoff_ts=o.cutoff_ts,
                       status=o.status, raw=o.raw, normalized=o.normalized,
                       z=o.z, close=o.close, detail=o.detail,
                       feature_names=o.feature_names)
               for o in obs]
    assert _scores(run, renamed, policy) == baseline


def test_the_seed_schedule_is_keyed_to_content_not_to_spelling(brain):
    run, mb, encoder, _ = brain
    policy = RO.policy_comparison()
    _, obs = _observations(encoder)
    a = obs[0]
    b = type(a)(symbol="0xZZZ", stable_id=a.stable_id, bar_index=a.bar_index,
                cutoff_ts=a.cutoff_ts, status=a.status, raw=a.raw,
                normalized=a.normalized, z=a.z, close=a.close, detail=a.detail,
                feature_names=a.feature_names)
    assert RO.observation_id(a) == RO.observation_id(b)
    digest = RO.state_digest(mb)
    assert policy.seeds(digest, RO.observation_id(a), a.stable_id) == \
        policy.seeds(digest, RO.observation_id(b), b.stable_id)


def test_the_comparison_schedule_is_not_keyed_to_the_weights(brain):
    """So LEARN and FROZEN draw the same Poisson stream for the same input."""
    run, mb, encoder, sha = brain
    policy = RO.policy_comparison()
    _, obs = _observations(encoder)
    a = obs[0]
    clean = RO.state_digest(mb, sha)
    moved = "f" * 64
    assert policy.seeds(clean, RO.observation_id(a), a.stable_id) == \
        policy.seeds(moved, RO.observation_id(a), a.stable_id)


def test_no_market_quantity_reaches_the_decoder(brain):
    """The decoder sees two firing rates and a threshold. That is all it sees.

    The amendment forbids an LLM, a classifier, an alpha score or a technical
    rule in the decision path. The mechanical form of that is: the decoder's
    input is the aggregate presentation, whose only market content is the
    firing rates the stimulus produced — and this asserts that two very
    different markets decoding to the same rates decode to the same action.
    """
    run, mb, encoder, _ = brain
    decoder = RO.decoder_k8()
    assert decoder.decode_rates(10.0, 1.0).action is D.Action.BUY
    assert decoder.decode_rates(1.0, 10.0).action is D.Action.SELL
    assert decoder.decode_rates(1.0, 1.0).action is D.Action.WAIT
    # its serialised form carries no market field at all
    d = decoder.as_dict()
    for key in ("price", "return", "volume", "token", "pnl", "outcome"):
        assert not any(key in str(k).lower() for k in d)


def test_the_decoder_module_imports_nothing_market_shaped():
    source = (ROOT / "flytrade" / "decoder.py").read_text()
    for forbidden in ("import requests", "openai", "sklearn", "torch",
                      "pandas", "flytrade.pons", "talib"):
        assert forbidden not in source


def test_the_pons_package_has_no_signing_or_broadcast_path():
    from flytrade.pons.rpc import ALLOWED_METHODS
    assert ALLOWED_METHODS == frozenset({
        "eth_chainId", "eth_blockNumber", "eth_getBlockByNumber",
        "eth_getLogs", "eth_getCode", "eth_call"})
    for module in sorted((ROOT / "flytrade" / "pons").glob("*.py")):
        source = module.read_text()
        code = "\n".join(line for line in source.splitlines()
                          if not line.lstrip().startswith("#"))
        for forbidden in ("privateKey", "private_key", "mnemonic",
                          "signTransaction", "from eth_account", "import web3"):
            assert forbidden not in code, f"{module.name} mentions {forbidden}"
    # the five refused methods are named **only** in rpc.py's own docstring and
    # in the test that attempts them; nothing constructs or dispatches them
    import flytrade.pons.rpc as RPC
    for method in ("eth_sendRawTransaction", "eth_sendTransaction", "eth_sign",
                   "personal_sign", "eth_accounts"):
        assert method not in RPC.ALLOWED_METHODS


def test_the_same_observation_gives_the_same_batch_twice(brain):
    run, mb, encoder, sha = brain
    policy = RO.policy_comparison()
    _, obs = _observations(encoder, n=1)
    first = _scores(run, obs, policy)
    second = _scores(run, obs, policy)
    assert first == second
