"""``pons_encoder_v2`` — the same olfactory pathway, a new declared schema.

docs/SPEC.md D11 amendment §4 and Fable addendum 4. ``pons_encoder_v1``
(:mod:`flytrade.pons.encoder`) is left **byte-identical** beside this module.

Nothing about the *pathway* changes: the same
:class:`flytrade.encoder.MarketToSensoryEncoder`, the same carrier, the same
constant drive budget, the same antagonistic glomerular pairs, no gain retune
and no decoder retune. What changes is the **input schema** — ten features
instead of eight, two of them new — and that is exactly the thing a learned
checkpoint cannot survive silently. A brain trained on sixteen channels whose
seventh pair meant *trades per minute* has no meaning for a twenty-channel map
whose seventh pair means *trades in the window* and whose eighth means *gross
volume*.

So the schema is named and hashed:

``encoder_version``      ``"pons_encoder_v2"``
``input_schema_sha256``  sha256 of the canonical JSON
                         ``{"features": [...], "scales": {...},
                         "channels": [...]}`` with sorted keys and no
                         whitespace.

Both ride in the **checkpoint metadata**, and
:func:`check_checkpoint_schema` refuses to continue learning from a checkpoint
whose metadata carries a different hash. The single exemption is a run declared
``from_clean_reference`` loading the clean reference itself, which predates the
field and is the only checkpoint allowed to lack it — and it is identified by
its recorded state digest, not by assertion.
"""

from __future__ import annotations

import hashlib
import json

from .. import encoder as E
from .context_v2 import PONS_FEATURES_V2, SINGLE_SIGNED
from .encoder import EXTENSION_POINTS, OLFACTORY, SensoryEncoder

VERSION = "pons_encoder_v2"


class SchemaMismatch(ValueError):
    """A checkpoint's input schema is not this encoder's. Never silent."""


def schema_sha256(features, scales, channels) -> str:
    """The hash rule, in one place.

    ``features`` is the **ordered** feature list, ``scales`` the declared
    positive scale of each, ``channels`` the glomerular channel map. Ordering
    of the feature list is significant and is preserved; the JSON keys are
    sorted so that two identical schemas written by two processes hash alike.
    """
    payload = json.dumps(
        {"features": [str(f) for f in features],
         "scales": {str(f): float(scales[f]) for f in features},
         "channels": channels},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SensoryEncoderV2(SensoryEncoder):
    """Versioned market context → modality-keyed stimuli. Olfactory only.

    Identical to :class:`flytrade.pons.encoder.SensoryEncoder` except for the
    default feature set, the version string and the schema hash it carries.
    """

    version = VERSION
    modalities = (OLFACTORY,)
    extension_points = EXTENSION_POINTS

    def __init__(self, ann, scales: dict, *,
                 features: tuple[str, ...] = PONS_FEATURES_V2,
                 min_upns: int = E.MIN_UPNS, **encoder_kw):
        super().__init__(ann, scales, features=features, min_upns=min_upns,
                         **encoder_kw)
        self.channels = self.olfactory.channel_table(self.ann)
        self.input_schema_sha256 = schema_sha256(
            self.features, self.scales, self.channels)

    # ------------------------------------------------------------ metadata
    def schema_metadata(self) -> dict:
        """What a checkpoint written under this encoder must carry."""
        return {"encoder_version": self.version,
                "input_schema_sha256": self.input_schema_sha256}

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "modalities": list(self.modalities),
            "extension_points": list(self.extension_points),
            "extension_points_implemented": False,
            "features": list(self.features),
            "features_requested": list(PONS_FEATURES_V2),
            "features_dropped": list(self.dropped),
            "single_signed": list(SINGLE_SIGNED),
            "normalisation": "tanh(raw / scale), fixed declared scales",
            "scales": dict(self.scales),
            "channels": self.channels,
            "input_schema_sha256": self.input_schema_sha256,
            "input_schema_rule": (
                "sha256 of the canonical JSON {\"features\": [ordered names], "
                "\"scales\": {name: scale}, \"channels\": [channel map]} with "
                "sorted keys and no whitespace"),
            "olfactory": self.olfactory.as_dict(),
        }


def check_checkpoint_schema(metadata: dict | None, *, input_schema_sha256: str,
                            encoder_version: str = VERSION,
                            from_clean_reference: bool = False,
                            checkpoint_digest: str | None = None,
                            clean_reference_digest: str | None = None) -> str:
    """Raise unless this checkpoint may be learned from under this schema.

    Returns the outcome as a string — ``"match"`` or
    ``"clean_reference_exemption"`` — so a caller can record which of the two
    happened rather than infer it from silence.

    The rule, from addendum 4:

    * metadata carrying **this** ``input_schema_sha256`` → continue;
    * metadata carrying a **different** one → raise, always;
    * metadata **lacking** the field → raise, unless the run is declared
      ``from_clean_reference`` **and** the checkpoint's own state digest is the
      declared clean reference's, which predates the field.

    A missing ``encoder_version`` beside a matching hash is accepted (the hash
    is the stronger statement); a *different* one beside a matching hash is
    refused, because two encoders that agree on features, scales and channels
    but disagree on their own name have a naming bug worth stopping for.
    """
    meta = dict(metadata or {})
    got = meta.get("input_schema_sha256")
    got_version = meta.get("encoder_version")
    if got == input_schema_sha256:
        if got_version is not None and str(got_version) != str(encoder_version):
            raise SchemaMismatch(
                f"checkpoint metadata names encoder {got_version!r} but the "
                f"schema hash is {encoder_version!r}'s; refusing to continue "
                f"learning from it")
        return "match"
    if got is None:
        if (from_clean_reference and clean_reference_digest is not None
                and checkpoint_digest is not None
                and str(checkpoint_digest) == str(clean_reference_digest)):
            return "clean_reference_exemption"
        raise SchemaMismatch(
            "checkpoint metadata carries no input_schema_sha256 and it is not "
            "the declared clean reference of a from_clean_reference run "
            f"(digest {str(checkpoint_digest)[:12]!r}, clean reference "
            f"{str(clean_reference_digest)[:12]!r}); refusing to continue "
            "learning from it")
    raise SchemaMismatch(
        f"checkpoint was written under input schema {str(got)[:12]}... and "
        f"this encoder is {input_schema_sha256[:12]}...; the learned weights "
        "address different sensory channels and continuing would be silent "
        "corruption")


__all__ = ["VERSION", "SensoryEncoderV2", "SchemaMismatch", "schema_sha256",
           "check_checkpoint_schema", "OLFACTORY", "EXTENSION_POINTS"]
