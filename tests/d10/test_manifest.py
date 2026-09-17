"""The deployment manifest: the chain literal, and the refusals it records.

The manifest is the only place that says which contract may be decoded with
which ABI. A wrong entry here is the "convenient but wrong ABI" the amendment
forbids, so the loader refuses a manifest it cannot vouch for rather than
working around it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from flytrade.pons.manifest import (CHAIN_ID, ManifestError, load_manifest,
                                    parse_manifest)

PATH = Path(__file__).resolve().parents[2] / "experiments" / "d10" / "deployments.json"


@pytest.fixture
def raw():
    return json.loads(PATH.read_text())


def test_the_committed_manifest_loads_and_names_one_supported_factory():
    manifest = load_manifest(PATH)
    assert manifest.chain_id == 4663 == CHAIN_ID
    assert manifest.factory.id == "pons-v2"
    assert manifest.factory.address == "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
    assert manifest.factory.expected_code_hash == (
        "0x89a27da6f703e0a7cdd4f233e7cb57604ff75b164530962d3ff7cf8483a67d84")
    assert manifest.factory.quote_assets == ("0x" + "0" * 40,)


def test_every_unsupported_entry_says_why_it_is_unsupported():
    manifest = load_manifest(PATH)
    unsupported = [d for d in manifest.deployments if not d.supported]
    assert {d.id for d in unsupported} == {"pons-v1", "pons-v1-legacy",
                                           "uniswap-v4-post-graduation"}
    for deployment in unsupported:
        assert deployment.reason


def test_a_different_chain_is_refused_outright(raw):
    raw["chain_id"] = 1
    with pytest.raises(ManifestError, match="chain_id"):
        parse_manifest(raw)


def test_duplicate_ids_and_addresses_are_refused(raw):
    doubled = copy.deepcopy(raw)
    doubled["deployments"].append(copy.deepcopy(doubled["deployments"][1]))
    with pytest.raises(ManifestError, match="duplicate"):
        parse_manifest(doubled)


def test_a_supported_entry_without_a_code_hash_is_refused(raw):
    raw["deployments"][0]["expected_code_hash"] = None
    with pytest.raises(ManifestError, match="code hash"):
        parse_manifest(raw)


def test_an_unsupported_entry_without_a_reason_is_refused(raw):
    raw["deployments"][1]["reason"] = None
    with pytest.raises(ManifestError, match="reason"):
        parse_manifest(raw)


def test_a_supported_entry_with_a_non_native_quote_is_refused(raw):
    raw["deployments"][0]["quote_assets"] = ["0x" + "1" * 40]
    with pytest.raises(ManifestError, match="native ETH"):
        parse_manifest(raw)


def test_two_supported_curve_factories_are_refused(raw):
    raw["deployments"][1]["supported"] = True
    raw["deployments"][1]["adapter"] = "curve"
    raw["deployments"][1]["quote_assets"] = ["0x" + "0" * 40]
    with pytest.raises(ManifestError, match="exactly one"):
        parse_manifest(raw)
