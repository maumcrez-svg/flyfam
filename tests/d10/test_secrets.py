"""Nothing this wave writes may contain the endpoint or the key.

docs/SPEC.md D10 addendum 17. The check is run against the files the wave has
actually produced — ``experiments/d10/``, ``data/MANIFEST.md`` and, when they are built,
``data/pons/d10-replay-v1/`` and ``data/pons/d10-backfill-v1/`` — using the
real endpoint read the real way, so a leak shows up as a failing test rather
than as a review.

The *name* of the environment variable is not a secret and is deliberately
recorded (addendum 4 asks for ``RPC_ENV_KEY`` in the config); its **value**,
the host it points at and every long token inside it are.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from flytrade.pons.rpc import DEFAULT_ENV_FILE, DEFAULT_ENV_KEY, RpcError, read_endpoint

ROOT = Path(__file__).resolve().parents[2]
TARGETS = [ROOT / "experiments" / "d10",
           ROOT / "data" / "pons" / "d10-replay-v1",
           ROOT / "data" / "pons" / "d10-backfill-v1",
           ROOT / "data" / "MANIFEST.md",
           ROOT / "flytrade" / "pons", ROOT / "tests" / "d10"]


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


def secrets():
    """The endpoint's value, its host and its path/query tokens."""
    try:
        url = read_endpoint(DEFAULT_ENV_FILE, DEFAULT_ENV_KEY)
    except RpcError:
        pytest.skip("no endpoint configured on this machine")
    parts = urlsplit(url)
    needles = {url}
    if parts.hostname:
        needles.add(parts.hostname)
    if parts.netloc:
        needles.add(parts.netloc)
    for segment in parts.path.split("/"):
        if len(segment) >= 12:
            needles.add(segment)
    if parts.query:
        needles.add(parts.query)
    return {n for n in needles if n}


def test_no_artifact_contains_the_endpoint_host_or_key():
    needles = secrets()
    assert needles
    offenders = []
    for path in artifacts():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover
            continue
        for needle in needles:
            if needle in text:
                offenders.append((str(path.relative_to(ROOT)), "<redacted needle>"))
                break
    assert offenders == []


def test_no_env_file_was_copied_into_the_repository():
    for path in artifacts():
        assert path.name != ".env"
        assert not path.name.endswith(".env")


def test_no_donor_env_file_is_read_by_this_package():
    """The donor's ``.env`` is never opened; only the one key, by name."""
    for path in (ROOT / "flytrade" / "pons").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Documentos/PONS" not in text
        assert ".env.example" not in text
