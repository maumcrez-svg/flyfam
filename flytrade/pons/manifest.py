"""The deployment manifest: what may be decoded, and what is refused by name.

docs/SPEC.md D10 addendum 3. ``experiments/d10/deployments.json`` is the
record; this module loads it and refuses a malformed one. The rules it
enforces are the ones a wrong answer would be expensive for:

* the chain literal is **4663** and nothing else runs on a different value;
* ids and addresses are unique and lower-cased;
* a supported entry carries an expected code hash to verify against
  ``eth_getCode``;
* an unsupported entry carries a **reason**, so "we did not price this" is a
  recorded decision rather than an omission.

Only ``pons-v2`` is supported this wave, with native ETH as the sole quote
asset. Anything else is recognised, recorded and never decoded with the curve
ABI (amendment section 4, addenda correction (d)).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CHAIN_ID = 4663
NATIVE_QUOTE = "0x0000000000000000000000000000000000000000"
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_HASH = re.compile(r"^0x[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest is not usable. Nothing on the network happens after this."""


@dataclass(frozen=True)
class Deployment:
    id: str
    adapter: str
    address: str
    role: str
    expected_code_hash: str | None
    status: str
    supported: bool
    quote_assets: tuple[str, ...]
    reason: str | None
    start_block: int | None
    raw: dict

    @property
    def is_v2_curve(self) -> bool:
        return self.supported and self.adapter == "curve"


@dataclass(frozen=True)
class Manifest:
    chain_id: int
    deployments: tuple[Deployment, ...]
    raw: dict

    def by_id(self, deployment_id: str) -> Deployment:
        for d in self.deployments:
            if d.id == deployment_id:
                return d
        raise ManifestError(f"no deployment {deployment_id!r}")

    def by_address(self, address: str) -> Deployment | None:
        address = str(address).lower()
        for d in self.deployments:
            if d.address == address:
                return d
        return None

    @property
    def supported(self) -> tuple[Deployment, ...]:
        return tuple(d for d in self.deployments if d.supported)

    @property
    def factory(self) -> Deployment:
        """The single supported factory. More than one is a manifest error."""
        supported = [d for d in self.supported if d.is_v2_curve]
        if len(supported) != 1:
            raise ManifestError(
                f"expected exactly one supported curve factory, got {len(supported)}")
        return supported[0]


def load_manifest(path) -> Manifest:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc.strerror}") from None
    except ValueError as exc:
        raise ManifestError(f"{path} is not JSON: {exc}") from None
    return parse_manifest(raw)


def parse_manifest(raw: dict) -> Manifest:
    if not isinstance(raw, dict):
        raise ManifestError("manifest is not an object")
    if raw.get("chain_id") != CHAIN_ID:
        raise ManifestError(
            f"chain_id must be the literal {CHAIN_ID}, got {raw.get('chain_id')!r}")
    entries = raw.get("deployments")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("manifest has no deployments")
    seen_ids: set[str] = set()
    seen_addresses: set[str] = set()
    parsed: list[Deployment] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ManifestError("deployment entry is not an object")
        ident = str(entry.get("id", ""))
        address = str(entry.get("address", "")).lower()
        if not re.fullmatch(r"[a-z0-9-]+", ident):
            raise ManifestError(f"bad deployment id {ident!r}")
        if not _ADDRESS.fullmatch(address):
            raise ManifestError(f"bad address for {ident!r}: {entry.get('address')!r}")
        if ident in seen_ids:
            raise ManifestError(f"duplicate deployment id {ident!r}")
        if address in seen_addresses:
            raise ManifestError(f"duplicate deployment address {address!r}")
        seen_ids.add(ident)
        seen_addresses.add(address)
        code_hash = entry.get("expected_code_hash")
        if code_hash is not None and not _HASH.fullmatch(str(code_hash).lower()):
            raise ManifestError(f"bad expected_code_hash for {ident!r}")
        supported = bool(entry.get("supported"))
        reason = entry.get("reason")
        if supported and code_hash is None:
            raise ManifestError(
                f"supported deployment {ident!r} needs a pinned code hash")
        if not supported and not reason:
            raise ManifestError(
                f"unsupported deployment {ident!r} must carry a reason")
        quotes = tuple(str(q).lower() for q in (entry.get("quote_assets") or ()))
        for quote in quotes:
            if not _ADDRESS.fullmatch(quote):
                raise ManifestError(f"bad quote asset {quote!r} for {ident!r}")
        if supported and quotes != (NATIVE_QUOTE,):
            raise ManifestError(
                f"{ident!r} is supported but its quote assets are not native ETH only")
        start = entry.get("start_block")
        parsed.append(Deployment(
            id=ident, adapter=str(entry.get("adapter", "")), address=address,
            role=str(entry.get("role", "")),
            expected_code_hash=None if code_hash is None else str(code_hash).lower(),
            status=str(entry.get("status", "")), supported=supported,
            quote_assets=quotes, reason=None if reason is None else str(reason),
            start_block=None if start is None else int(start), raw=entry))
    manifest = Manifest(chain_id=CHAIN_ID, deployments=tuple(parsed), raw=raw)
    manifest.factory  # raises unless exactly one supported curve factory
    return manifest
