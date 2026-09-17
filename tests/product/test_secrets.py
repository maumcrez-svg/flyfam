"""Nothing this wave writes may contain the endpoint or the key. P1 addendum 4.

``tests/d10/test_secrets.py`` is this check for the D10 wave; this is the same
check, with the same real endpoint read the same real way, extended to every
file P1 adds — the committed ones **and** the runtime ones under
``data/pons/live/``, which is where the feed a spectacle reads actually lives.

The *name* of the environment variable is not a secret and is deliberately
recorded in ``product/pons_live.json`` and in the unit file; its **value**, the
host it points at and every long token inside it are.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from flytrade.pons.rpc import (DEFAULT_ENV_FILE, DEFAULT_ENV_KEY, RpcError,
                               read_endpoint)
from tests.d10.test_secrets import secrets

ROOT = Path(__file__).resolve().parents[2]
TARGETS = [ROOT / "brains", ROOT / "product", ROOT / "scripts",
           ROOT / "flytrade" / "product", ROOT / "tests" / "product",
           ROOT / "docs" / "SPECTACLE_FEED.md",
           ROOT / "data" / "pons" / "live",
           Path.home() / ".config" / "systemd" / "user" / "the-pons-user-unit"]

#: the runtime files a spectacle actually reads
FEED_FILES = [ROOT / "data" / "pons" / "live" / "state.json"]


def artifacts():
    for target in TARGETS:
        if not target.exists():
            continue
        if target.is_file():
            yield target
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                yield path


def test_there_are_artifacts_to_check():
    """A vacuous pass is not a pass."""
    names = {p.name for p in artifacts()}
    assert {"brain.npz", "manifest.json", "pons_live.json", "run.py",
            "the live-loop launcher", "SPECTACLE_FEED.md"} <= names


def test_no_artifact_contains_the_endpoint_host_or_key():
    needles = secrets()
    assert needles
    offenders = []
    for path in artifacts():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:                                    # pragma: no cover
            continue
        for needle in needles:
            if needle in text:
                offenders.append((str(path.relative_to(ROOT)
                                      if ROOT in path.parents else path),
                                  "<redacted needle>"))
                break
    assert offenders == []


def test_no_env_file_was_copied_into_the_repository():
    for path in artifacts():
        assert path.name != ".env"
        assert not path.name.endswith(".env")


def test_the_feed_carries_no_url_at_all():
    """Not only the real endpoint: no http(s) URL and no bearer-shaped token."""
    for path in artifacts():
        if path.suffix not in (".json", ".jsonl") or "live" not in str(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.findall(r"https?://[^\s\"']+", text):
            assert match.startswith("<rpc-endpoint>"), match
        assert "Authorization" not in text
        assert "Bearer " not in text


def test_the_masked_placeholder_is_what_an_error_would_carry():
    from flytrade.pons.rpc import MASK, mask
    try:
        url = read_endpoint(DEFAULT_ENV_FILE, DEFAULT_ENV_KEY)
    except RpcError:                                       # pragma: no cover
        pytest.skip("no endpoint configured on this machine")
    assert mask(f"connection to {url} failed", url).count(MASK) >= 1
    assert url not in mask(f"connection to {url} failed", url)


def test_the_state_file_names_no_person():
    """No PII: the feed is chain addresses, prices and the loop's own health."""
    for path in FEED_FILES:
        if not path.exists():
            continue
        state = json.loads(path.read_text())
        flat = json.dumps(state)
        assert "@" not in flat.replace("@example", "")      # no address-like PII
        assert "maumcrez" not in flat
        assert "/home/" not in flat
