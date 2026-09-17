"""The hand decoder: every topic recomputed, every shape refused.

The declarations in :mod:`flytrade.pons.abi` are copied from the donor's
``src/adapters.ts``. That is a claim, and this file is what turns it into a
check: each ``topic0`` is recomputed by keccak-256 from the canonical
signature and compared with the donor's frozen ``config/event-evidence.json``,
which itself pins the PONS source commit and the Sourcify factory match.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from flytrade.pons import abi
from flytrade.pons.rpc import keccak256_hex
from tests.d10.scripted import (BUYER, CURVE, TOKEN, buy_log, curve_event,
                                factory_event, launch_log, make_log)

EVIDENCE = Path(__file__).resolve().parents[2] / "experiments" / "d10" / "evidence"
ALL_EVENTS = (abi.V2_FACTORY_EVENTS + abi.CURVE_EVENTS + abi.V1_FACTORY_EVENTS
              + abi.V3_POOL_EVENTS)


def canonical(declaration: str) -> str:
    """``event Name( type indexed a, type b );`` -> ``Name(type,type)``."""
    text = " ".join(declaration.split()).rstrip(";")
    name = re.match(r"event\s+([A-Za-z0-9_]+)\s*\(", text).group(1)
    inside = text[text.index("(") + 1:text.rindex(")")]
    types = []
    for part in inside.split(","):
        words = part.split()
        if words:
            types.append(words[0])
    return f"{name}({','.join(types)})"


def test_every_pinned_topic0_is_reproduced_from_its_signature():
    evidence = json.loads((EVIDENCE / "event-evidence.json").read_text())
    pinned = {m["topic0"]: m["declaration"] for m in evidence["mapped"]
              if "topic0" in m}
    assert len(pinned) == 8
    ours = {event.topic0: event.signature for event in ALL_EVENTS}
    for topic0, declaration in pinned.items():
        assert topic0 in ours, declaration
        assert ours[topic0] == canonical(declaration)
        assert keccak256_hex(ours[topic0].encode()) == topic0


def test_every_declaration_in_the_evidence_file_parses_to_one_of_ours():
    evidence = json.loads((EVIDENCE / "event-evidence.json").read_text())
    signatures = {event.signature for event in ALL_EVENTS}
    for entry in evidence["mapped"]:
        assert canonical(entry["declaration"]) in signatures, entry["declaration"]


def test_the_observed_token_launched_topic_matches_the_chain():
    # The topic0 seen on every one of the 1,136 launches the donor collected.
    assert factory_event("TokenLaunched").topic0 == (
        "0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607")


def test_no_two_events_in_one_registry_share_a_topic():
    for registry in (abi.V2_FACTORY_EVENTS, abi.CURVE_EVENTS):
        topics = [event.topic0 for event in registry]
        assert len(topics) == len(set(topics))


def test_a_launch_decodes_into_its_named_fields():
    decoded = abi.decode_factory_log(launch_log())
    assert decoded["event"] == "TokenLaunched"
    assert decoded["args"]["token"] == TOKEN
    assert decoded["args"]["curve"] == CURVE
    assert decoded["args"]["pairToken"] == "0x" + "0" * 40
    assert decoded["args"]["graduationThreshold"] == 4_200_000_000_000_000_000


def test_a_buy_decodes_with_uint256_precision():
    quote_in = 10 ** 16
    tokens_out = 2 ** 200 - 1        # far beyond a float or a JSON number
    decoded = abi.decode_curve_log(
        buy_log(103, quote_in, tokens_out, 10 ** 14, 2 * 10 ** 14))
    assert decoded["event"] == "CurveBuy"
    assert decoded["args"]["tokensOut"] == tokens_out
    assert decoded["args"]["buyer"] == BUYER


def test_extra_topics_are_a_shape_mismatch():
    log = buy_log(103, 1, 2, 3, 4)
    log["topics"] = log["topics"] + ["0x" + "0" * 64]
    decoded = abi.decode_curve_log(log)
    assert decoded["event"] == "decode-error"
    assert "ABI_SHAPE_MISMATCH" in decoded["error"]


def test_trailing_data_is_a_shape_mismatch():
    log = buy_log(103, 1, 2, 3, 4)
    log["data"] = log["data"] + "00" * 32
    assert abi.decode_curve_log(log)["event"] == "decode-error"


def test_truncated_data_is_a_shape_mismatch():
    log = buy_log(103, 1, 2, 3, 4)
    log["data"] = log["data"][:-64]
    assert abi.decode_curve_log(log)["event"] == "decode-error"


def test_a_dirty_address_word_is_refused():
    log = make_log(address=CURVE, event=curve_event("Initialized"),
                   indexed=[], data_values=[TOKEN], block=101)
    log["data"] = "0x" + "ff" * 12 + log["data"][2 + 24:]
    assert abi.decode_curve_log(log)["event"] == "decode-error"


@pytest.mark.parametrize("event", abi.V1_FACTORY_EVENTS + abi.V3_POOL_EVENTS)
def test_v1_and_v3_events_are_recognised_and_refused_not_decoded(event):
    assert event.topic0 in abi.UNSUPPORTED_TOPICS
    log = make_log(address=CURVE, event=event,
                   indexed=[0] * len(event.indexed),
                   data_values=[0] * len(event.unindexed), block=101)
    decoded = abi.decode_curve_log(log)
    assert decoded["event"] == "unsupported"
    assert decoded["args"] == {}
    assert decoded["recognised_as"] == event.signature
    assert decoded["reason"]


def test_the_two_token_launched_events_are_different_topics():
    v1 = abi.V1_FACTORY_EVENTS[0]
    v2 = factory_event("TokenLaunched")
    assert v1.name == v2.name == "TokenLaunched"
    assert v1.topic0 != v2.topic0


def test_an_unknown_topic_is_unmapped_not_guessed():
    log = buy_log(103, 1, 2, 3, 4)
    log["topics"][0] = "0x" + "ab" * 32
    decoded = abi.decode_curve_log(log)
    assert decoded["event"] == "unmapped"
    assert decoded["args"] == {}
