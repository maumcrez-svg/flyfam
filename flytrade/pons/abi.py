"""Hand decoding of the PONS v2 events, and refusal to decode the others.

docs/SPEC.md D10 addendum 4: no ``eth-abi``, no ``web3``. Every event this
wave reads has a static layout — fixed-width words, no dynamic types — so a
decoder is topic words plus 32-byte data words plus the shape checks the donor
already applies in ``src/adapters.ts`` (``ABI_SHAPE_MISMATCH`` on extra topics
or trailing data). The declarations below are copied from that file, which
pins them to PONS source commit ``8b9bf371030279133017b5c1b713823f5889c5d2``
and to the Sourcify-verified factory bundle; ``experiments/d10/evidence/``
holds the frozen copies and ``tests/d10/test_abi.py`` recomputes every
``topic0`` by keccak-256 and compares it with ``event-evidence.json``.

**What is deliberately not decoded** (addendum 4 and correction (d)): the v1
factory's ``TokenLaunched`` and the Uniswap V3 pool's ``Swap`` / ``Mint`` /
``Burn``. They are recognised by ``topic0`` and mapped to ``unsupported`` with
a reason, never decoded as curve events. A v1 launch is a Uniswap V3 route
that this wave does not price, and a convenient-but-wrong ABI is exactly the
failure mode the amendment forbids.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rpc import keccak256_hex

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class AbiError(ValueError):
    """A log did not have the shape its declared event requires."""


@dataclass(frozen=True)
class Input:
    type: str
    name: str
    indexed: bool = False


@dataclass(frozen=True)
class Event:
    name: str
    inputs: tuple[Input, ...]

    @property
    def signature(self) -> str:
        return f"{self.name}({','.join(i.type for i in self.inputs)})"

    @property
    def topic0(self) -> str:
        return keccak256_hex(self.signature.encode("ascii"))

    @property
    def indexed(self) -> tuple[Input, ...]:
        return tuple(i for i in self.inputs if i.indexed)

    @property
    def unindexed(self) -> tuple[Input, ...]:
        return tuple(i for i in self.inputs if not i.indexed)


def _e(name: str, *inputs) -> Event:
    parsed = []
    for spec in inputs:
        parts = spec.split()
        if len(parts) == 3 and parts[1] == "indexed":
            parsed.append(Input(parts[0], parts[2], True))
        elif len(parts) == 2:
            parsed.append(Input(parts[0], parts[1], False))
        else:  # pragma: no cover - a typo in this file, not a runtime path
            raise AbiError(f"bad input declaration {spec!r}")
    return Event(name, tuple(parsed))


# --------------------------------------------------------------------------
# PONS v2 launch factory (adapter ``curve``), src/adapters.ts::v2Abi
# --------------------------------------------------------------------------
V2_FACTORY_EVENTS: tuple[Event, ...] = (
    _e("CreatorFeeRecipientUpdated", "address indexed token",
       "address indexed previousRecipient", "address indexed newRecipient"),
    _e("GraduationTokensPermanentlyLocked", "address indexed token",
       "uint256 amount"),
    _e("TokenLaunched", "address indexed token", "address indexed curve",
       "address indexed deployer", "address pairToken", "uint256 launchConfigId",
       "uint256 graduationThreshold"),
    _e("LaunchSwept", "address indexed token", "uint256 quoteOut",
       "uint256 tokenOut"),
    _e("PoolGraduated", "address indexed token", "uint256 positionId",
       "uint256 tokenAmount", "uint256 pairTokenAmount"),
    _e("LaunchGraduationRescued", "address indexed token",
       "address indexed recipient", "uint256 quoteAmount", "uint256 tokenAmount"),
)

# --------------------------------------------------------------------------
# PONS v2 bonding curve, src/adapters.ts::curveAbi
# --------------------------------------------------------------------------
CURVE_EVENTS: tuple[Event, ...] = (
    _e("AutoGraduationFailed", "address indexed token", "uint256 gasRemaining"),
    _e("BuybackEnabledUpdated", "bool enabled"),
    _e("FeesRescued", "address indexed protocolRecipient",
       "address indexed creatorRecipient", "uint256 protocolAmount",
       "uint256 creatorAmount"),
    _e("BuybackLocked", "uint256 quoteSpent", "uint256 tokensLocked"),
    _e("CreatorFeeRecipientUpdated", "address indexed previousRecipient",
       "address indexed newRecipient"),
    _e("SnipeTaxCharged", "address indexed recipient", "uint256 amount"),
    _e("FeesSwept", "uint256 protocolAmount", "uint256 buybackAmount",
       "uint256 creatorAmount"),
    _e("Initialized", "address token"),
    _e("SnipeTaxExempted", "address indexed account"),
    _e("CurveBuy", "address indexed buyer", "address indexed recipient",
       "uint256 quoteIn", "uint256 tokensOut", "uint256 fee", "uint256 tax"),
    _e("CurveSell", "address indexed seller", "address indexed recipient",
       "uint256 tokensIn", "uint256 quoteOut", "uint256 fee", "uint256 tax"),
    _e("CurveBuyRefunded", "address indexed buyer", "uint256 refund"),
    _e("CurveCompleted", "address recipient", "uint256 quoteOut",
       "uint256 tokenOut"),
)

# --------------------------------------------------------------------------
# Recognised and refused. Never decoded with the curve ABI.
# --------------------------------------------------------------------------
V1_FACTORY_EVENTS: tuple[Event, ...] = (
    _e("TokenLaunched", "address indexed token", "address indexed deployer",
       "address indexed dexFactory", "address pairToken", "address pool",
       "uint256 dexId", "uint256 launchConfigId", "uint256 positionId",
       "uint256 restrictionsEndBlock", "uint256 initialBuyAmount"),
)

V3_POOL_EVENTS: tuple[Event, ...] = (
    _e("Swap", "address indexed sender", "address indexed recipient",
       "int256 amount0", "int256 amount1", "uint160 sqrtPriceX96",
       "uint128 liquidity", "int24 tick"),
    _e("Mint", "address sender", "address indexed owner",
       "int24 indexed tickLower", "int24 indexed tickUpper", "uint128 amount",
       "uint256 amount0", "uint256 amount1"),
    _e("Burn", "address indexed owner", "int24 indexed tickLower",
       "int24 indexed tickUpper", "uint128 amount", "uint256 amount0",
       "uint256 amount1"),
)

#: topic0 -> (event, why it is not priced this wave)
UNSUPPORTED_TOPICS: dict[str, tuple[Event, str]] = {
    **{e.topic0: (e, "PONS v1 route is Uniswap V3, not priced this wave")
       for e in V1_FACTORY_EVENTS},
    **{e.topic0: (e, "Uniswap V3 pool event, not priced this wave")
       for e in V3_POOL_EVENTS},
}


def topic_index(events) -> dict[str, Event]:
    index: dict[str, Event] = {}
    for event in events:
        topic = event.topic0
        if topic in index:  # pragma: no cover - would be a signature collision
            raise AbiError(f"topic0 collision on {event.signature}")
        index[topic] = event
    return index


V2_FACTORY_BY_TOPIC = topic_index(V2_FACTORY_EVENTS)
CURVE_BY_TOPIC = topic_index(CURVE_EVENTS)


# ---------------------------------------------------------------- decoding
def _word(data: bytes, i: int) -> bytes:
    return data[i * 32:(i + 1) * 32]


def _decode_word(kind: str, word: bytes):
    if len(word) != 32:
        raise AbiError("short word")
    if kind == "address":
        if any(word[:12]):
            raise AbiError("address word has dirty high bytes")
        return "0x" + word[12:].hex()
    if kind == "bool":
        if any(word[:31]) or word[31] not in (0, 1):
            raise AbiError("bool word is not 0 or 1")
        return bool(word[31])
    if kind.startswith("uint"):
        bits = int(kind[4:] or 256)
        value = int.from_bytes(word, "big")
        if value >> bits:
            raise AbiError(f"{kind} out of range")
        return value
    if kind.startswith("int"):
        bits = int(kind[3:] or 256)
        value = int.from_bytes(word, "big", signed=True)
        if not (-(1 << (bits - 1)) <= value < (1 << (bits - 1))):
            raise AbiError(f"{kind} out of range")
        return value
    raise AbiError(f"unsupported static type {kind!r}")  # pragma: no cover


def _hex_to_bytes(data: str) -> bytes:
    text = str(data)
    if not text.startswith("0x") or len(text) % 2:
        raise AbiError("data is not 0x-prefixed even-length hex")
    try:
        return bytes.fromhex(text[2:])
    except ValueError:
        raise AbiError("data is not hex") from None


def decode_log(log: dict, by_topic: dict[str, Event]) -> dict:
    """Decode one log against a topic index. Never raises for an unknown event.

    Returns ``{"event", "args", "error"}``. ``event`` is ``"unmapped"`` when
    the topic is not in the index, ``"unsupported"`` when it belongs to a
    recognised but unpriced route, ``"decode-error"`` when the shape is wrong.
    """
    topics = [str(t).lower() for t in (log.get("topics") or [])]
    if not topics:
        return {"event": "unmapped", "args": {}, "error": "NO_TOPICS"}
    topic0 = topics[0]
    event = by_topic.get(topic0)
    if event is None:
        known = UNSUPPORTED_TOPICS.get(topic0)
        if known is not None:
            return {"event": "unsupported", "args": {},
                    "error": None, "recognised_as": known[0].signature,
                    "reason": known[1]}
        return {"event": "unmapped", "args": {}, "error": None}
    try:
        data = _hex_to_bytes(log.get("data", "0x"))
        # Strict shape, exactly as the donor's decodeStaticEvent: no extra
        # topics, no trailing data, no truncation. Every supported event is
        # static, so the two counts are exact, not lower bounds.
        if len(topics) != 1 + len(event.indexed):
            raise AbiError("ABI_SHAPE_MISMATCH: topic count")
        if len(data) != 32 * len(event.unindexed):
            raise AbiError("ABI_SHAPE_MISMATCH: data length")
        args: dict = {}
        for i, spec in enumerate(event.indexed):
            args[spec.name] = _decode_word(spec.type, bytes.fromhex(topics[i + 1][2:]))
        for i, spec in enumerate(event.unindexed):
            args[spec.name] = _decode_word(spec.type, _word(data, i))
    except (AbiError, ValueError) as exc:
        return {"event": "decode-error", "args": {},
                "error": f"ABI_DECODE_FAILED: {exc}"}
    return {"event": event.name, "args": args, "error": None}


def decode_factory_log(log: dict) -> dict:
    """Decode against the **v2** factory ABI, recognising the v1 one as unsupported."""
    return decode_log(log, V2_FACTORY_BY_TOPIC)


def decode_curve_log(log: dict) -> dict:
    """Decode against the curve ABI, recognising V3 pool events as unsupported."""
    return decode_log(log, CURVE_BY_TOPIC)
