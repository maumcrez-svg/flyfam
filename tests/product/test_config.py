"""The one committed configuration, and what P1 promised not to move.

P1 addendum 1 and 7: no threshold, scale, admission constant or reinforcement
scale changes, no school mode, no plasticity, no signing, and only the six
read-only RPC methods that were already allowlisted.
"""

from __future__ import annotations

import ast
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "product" / "pons_live.json").read_text())
D11_RUN = json.loads((ROOT / "experiments" / "d11" / "d11_001.json").read_text())
D11_CFG = ROOT / "experiments" / "d11" / "config.json"
MANIFEST = json.loads((ROOT / "brains" / "trader-v1" / "manifest.json").read_text())

PRODUCT_SOURCES = sorted(
    list((ROOT / "flytrade" / "product").glob("*.py"))
    + [ROOT / "product" / "run.py", ROOT / "product" / "freeze.py"])


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_every_restated_number_is_d11s_own():
    """The product file is readable alone; it may not invent a number."""
    mine = CONFIG["fixed_for_the_whole_wave"]
    theirs = D11_RUN["fixed_for_the_whole_wave"]
    for key in ("horizon_seconds", "cadence_seconds", "max_candidates_per_round",
                "readout_k", "readout_namespace", "paper_size_wei",
                "latency_seconds", "initial_cash_eth", "admission", "context",
                "encoder", "reinforce_full_scale", "reinforce_cap"):
        assert mine[key] == theirs[key], key
    assert mine["gas_wei"] == theirs["gas_wei"]
    assert mine["max_open_positions"] == theirs["max_open_positions"] == 1
    assert mine["track_seconds"] == json.loads(D11_CFG.read_text())[
        "admission"]["track_seconds"]


def test_the_d11_configuration_is_the_one_the_artifact_was_built_against():
    """A moved scale or admission constant would break this hash."""
    got = sha256_file(D11_CFG)
    assert got == CONFIG["environment"]["d11_config_sha256"]
    assert got == MANIFEST["d11_config"]["sha256"]


def test_the_brain_is_the_registered_clean_reference_everywhere():
    digest = "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5"
    assert CONFIG["brain"]["state_digest"] == digest
    assert MANIFEST["state_digest"] == digest
    assert json.loads(D11_CFG.read_text())["next_run"][
        "clean_reference_checkpoint"]["state_digest"] == digest
    assert D11_RUN["fixed_for_the_whole_wave"][
        "clean_reference_state_digest"] == digest
    assert CONFIG["learning"] == MANIFEST["learning"] == "FROZEN"


def test_the_settlement_constants_are_d10s_live_ones():
    d10 = json.loads((ROOT / "experiments" / "d10" / "config.json").read_text())
    assert (CONFIG["settlement"]["confirm_depth_blocks"]
            == d10["settlement"]["confirm_depth_blocks"])
    assert (CONFIG["settlement"]["safe_tag_supported"]
            == d10["settlement"]["safe_tag_supported"])
    assert (CONFIG["settlement"]["median_block_interval_s"]
            == d10["dataset"]["window"]["median_block_interval_s"])
    assert CONFIG["admission"]["require_coverage"] is False


def test_the_hourly_cap_is_a_rolling_window_and_never_a_stop():
    limits = CONFIG["limits"]
    assert limits["hourly_request_cap"] == 3000
    assert limits["window_seconds"] == 3600
    assert limits["no_wall_clock_stop"] is True
    # the ledger's own caps are backstops above what the hourly cap can pass
    assert limits["ledger_caps"]["day"] > 24 * limits["hourly_request_cap"]
    assert limits["ledger_caps"]["run"] > 24 * limits["hourly_request_cap"]


def test_the_product_names_no_method_outside_the_allowlist():
    from flytrade.pons.rpc import ALLOWED_METHODS
    for path in PRODUCT_SOURCES:
        for name in ("eth_sendRawTransaction", "eth_sendTransaction", "eth_sign",
                     "personal_sign", "eth_accounts", "eth_signTransaction"):
            assert name not in path.read_text(), f"{path.name} names {name}"
    import re
    named = set()
    for path in PRODUCT_SOURCES:
        named |= set(re.findall(r"\beth_[A-Za-z]+", path.read_text()))
    assert named <= set(ALLOWED_METHODS), named - set(ALLOWED_METHODS)


def test_the_product_signs_nothing():
    for path in PRODUCT_SOURCES:
        text = path.read_text()
        for word in ("private_key", "privateKey", "mnemonic", "keystore",
                     "sign_transaction", "send_raw", "wallet"):
            assert word not in text, f"{path.name} names {word}"


def test_nothing_in_the_product_applies_a_weight_update():
    """FROZEN is not a promise here; it is the absence of a call."""
    for path in PRODUCT_SOURCES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            assert name not in ("forget", "depress", "potentiate"), path.name
            if name == "settle" and isinstance(fn, ast.Attribute):
                base = getattr(fn.value, "attr", None) or getattr(fn.value, "id", "")
                assert base != "credit", f"{path.name} applies a credit"
    live = (ROOT / "flytrade" / "product" / "live.py").read_text()
    assert "learning=LOOP.FROZEN" in (ROOT / "product" / "run.py").read_text()
    assert "the product loop runs FROZEN and only FROZEN" in live
    assert "applied=False" in live


def test_the_product_never_selects_school_mode_or_the_relative_teacher():
    for path in PRODUCT_SOURCES:
        text = path.read_text()
        assert "relative_cohort" not in text
        assert "RELATIVE_COHORT" not in text
        # `freeze.py` names the school once, in prose, saying the artifact is
        # the checkpoint it started from; nothing imports or selects it
        assert "school.py" not in text
        assert "d12lib" not in text
    assert CONFIG["credit"]["rule"].startswith("absolute_profit_v1")
    from flytrade.product import live as PL
    assert PL.ABSOLUTE_PROFIT_V1 == "absolute_profit_v1"


def test_the_nine_kinds_are_declared_in_the_projection():
    import sys
    sys.path.insert(0, str(ROOT / "observer"))
    import projection as P                                # noqa: PLC0415

    from flytrade import records as REC
    from flytrade.product import feed as FEED
    assert set(FEED.KINDS) <= set(P.KINDS)
    assert set(P.KINDS) == {e.value for e in REC.EventType}
    assert set(CONFIG["feed"]["kinds"]) == set(FEED.KINDS)


def test_the_configuration_says_what_it_is_not():
    assert "no hypothesis" in CONFIG["this_is_not_an_experiment"]
    assert CONFIG["credit"]["recorded_never_applied"].startswith(
        "every settled episode")
    assert CONFIG["endpoint"]["signing"].startswith("there is none")
