"""One JSON-RPC endpoint, standard library only, with no way to sign anything.

docs/SPEC.md D10 addendum 4. The rules, in the order they bite:

* **Method allowlist.** Six read methods. Everything else raises
  ``RPC_METHOD_NOT_ALLOWED`` *before a socket is opened*. There is no signing
  code and no key material anywhere in ``flytrade/``; the allowlist is the
  mechanical half of that proof and :mod:`tests.d10.test_rpc` attempts the
  five signing/broadcast methods against it.
* **One endpoint, read by key name at runtime.** The URL is never printed,
  logged or written to an artifact. :func:`mask` is applied to every string
  that can leave this module.
* **No retry, no fallback, no provider switch.** A transport failure is an
  error, not an invitation. HTTP 429 or a provider quota message halts the
  process with the ledger persisted. D11-001 addendum 4 adds the endpoint's
  *class*: :func:`flytrade.pons.budget.endpoint_class` sorts a URL into
  ``loopback`` or ``remote`` by host, the ledger is told which one it is
  **before the client can make a request**, and a ledger opened in loopback
  scope refuses a remote endpoint outright. A wave collecting through the
  local node therefore cannot spend a remote unit by accident, and it still
  cannot switch provider on an error.
* **15 second timeout.**

The client owns the ledger (:mod:`flytrade.pons.budget`) and charges every
attempt to it, archive-weighted against the head it knew at call time.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from .budget import BudgetStop, RequestLedger, archive_units, endpoint_class

#: The only methods this project may ever call. No ``eth_sendRawTransaction``,
#: no ``eth_sendTransaction``, no ``eth_sign``, no ``personal_sign``, no
#: ``eth_accounts`` — and no way to add one at runtime.
ALLOWED_METHODS = frozenset({
    "eth_chainId",
    "eth_blockNumber",
    "eth_getBlockByNumber",
    "eth_getLogs",
    "eth_getCode",
    "eth_call",
})

TIMEOUT_S = 15.0

#: Substrings that mean "the provider is refusing us on quota" — the account
#: is out of requests and every further call this wave makes would be refused
#: too. Narrowed after dispatch 1 (docs/SPEC.md, reviewer decision 1): the
#: donor's regex carried a bare ``limit exceeded``, which is also how a
#: provider says *this one request asked for too much*. A range refusal must
#: not halt a wave, so ``limit exceeded`` moved to :data:`_RANGE_RE` and this
#: pattern now only matches account-level refusals.
_QUOTA_RE = re.compile(
    r"quota"
    r"|credits?\s+(?:exhausted|depleted)"
    r"|out of (?:credits|requests)"
    r"|rate.?limit|too many requests"
    r"|payment required"
    r"|max(?:imum)?\s+(?:monthly|daily|plan)\s+usage",
    re.IGNORECASE)

#: Substrings that mean "**this** request asked for too many blocks or
#: returned too much" — a per-request refusal, curable by asking for less.
#: Reviewer decision 1: it raises :data:`RANGE_TOO_LARGE`, the collector
#: halves its chunk down to :data:`MIN_CHUNK_BLOCKS` and then stops, and every
#: attempt is counted in the ledger. It never halts the wave.
_RANGE_RE = re.compile(
    r"block range|range too|too (?:wide|large) a range|too many blocks"
    r"|query returned more than|more than \d+ results"
    r"|logs? matched (?:by )?th(?:is|e) request"
    r"|exceeds? (?:the )?(?:maximum|limit)|limit exceeded"
    r"|response size|result set too large"
    r"|too many (?:logs|results|matches)",
    re.IGNORECASE)

#: The code a range/size refusal is reported under, distinct from a quota halt.
RANGE_TOO_LARGE = "RPC_RANGE_TOO_LARGE"


def classify_provider_error(message: str) -> str | None:
    """``"QUOTA"``, ``"RANGE"`` or ``None`` for one provider error message.

    Quota is tested first and its pattern is narrow, so a range message can
    never be read as a spent account; a message that is neither is an ordinary
    ``RPC_ERROR_<code>`` and is not retried either.
    """
    text = str(message)
    if _QUOTA_RE.search(text):
        return "QUOTA"
    if _RANGE_RE.search(text):
        return "RANGE"
    return None

MASK = "<rpc-endpoint>"

DEFAULT_ENV_FILE = ".env"
DEFAULT_ENV_KEY = "CHAINSTACK_RPC_HTTPS_KEYED"


class RpcError(RuntimeError):
    """A JSON-RPC or transport failure, already masked."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def read_endpoint(env_file: str = DEFAULT_ENV_FILE,
                  env_key: str = DEFAULT_ENV_KEY) -> str:
    """Read the endpoint out of a dotenv file **by key name only**.

    Nothing else in that file is read, kept or copied; the donor's ``.env`` is
    never touched (addendum 17). The returned string is a secret: it must not
    be logged, printed or written anywhere. :class:`RpcClient` takes it and
    keeps it private.
    """
    path = Path(env_file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RpcError("RPC_ENV_UNREADABLE", f"{env_file}: {exc.strerror}") from None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != env_key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value:
            break
        return value
    raise RpcError("RPC_NOT_CONFIGURED", f"{env_key} absent from {env_file}")


def mask(text: str, url: str | None = None) -> str:
    """Replace the endpoint, its host and anything key-shaped with a placeholder.

    Three layers, because one is not enough: the exact URL, its host, and any
    remaining long opaque path or query token. Applied to every error string,
    every artifact field and every log line this package produces.
    """
    out = str(text)
    if url:
        out = out.replace(url, MASK)
        try:
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            if parts.hostname:
                out = out.replace(parts.hostname, MASK)
            if parts.netloc:
                out = out.replace(parts.netloc, MASK)
            for segment in parts.path.split("/"):
                if len(segment) >= 12:
                    out = out.replace(segment, MASK)
            if parts.query:
                out = out.replace(parts.query, MASK)
        except ValueError:
            pass
    # Belt and braces: any https URL at all, and any long hex/base58-ish run.
    out = re.sub(r"https?://[^\s\"'<>]+", MASK, out)
    out = re.sub(r"\b[0-9a-zA-Z_-]{24,}\b", MASK, out)
    return out


def _hexnum(value: int) -> str:
    return hex(int(value))


def _queried_block(method: str, params: list) -> int | None:
    """Which block a call reads, for archive weighting. ``None`` when unknown."""
    def parse(tag):
        if isinstance(tag, int):
            return tag
        if isinstance(tag, str) and tag.startswith("0x"):
            try:
                return int(tag, 16)
            except ValueError:
                return None
        return None

    if method == "eth_getBlockByNumber" and params:
        return parse(params[0])
    if method in ("eth_getCode", "eth_call") and len(params) >= 2:
        return parse(params[1])
    if method == "eth_getLogs" and params and isinstance(params[0], dict):
        return parse(params[0].get("toBlock"))
    return None


class RpcClient:
    """A read-only JSON-RPC client over ``urllib``.

    ``url`` is held privately and never exposed; :attr:`masked_url` is what any
    caller may show. ``opener`` exists so tests can script the transport
    without a socket (``tests/d10/scripted.py``).
    """

    def __init__(self, url: str, ledger: RequestLedger, *, timeout: float = TIMEOUT_S,
                 opener=None):
        self._url = str(url)
        self.ledger = ledger
        self.timeout = float(timeout)
        self._opener = opener
        self.known_head: int | None = None
        # D11-001 addendum 4: the ledger classifies the endpoint and may refuse
        # it, here, before this client can open anything. A ledger without the
        # method is a D5-D10 ledger and is left exactly as it was.
        admit = getattr(self.ledger, "admit", None)
        self.endpoint_class = (admit(self._url) if admit is not None
                               else endpoint_class(self._url))

    # ------------------------------------------------------------- masking
    @property
    def masked_url(self) -> str:
        return MASK

    def mask(self, text) -> str:
        return mask(text, self._url)

    # ----------------------------------------------------------- transport
    def _post(self, body: bytes) -> tuple[int, bytes]:
        if self._opener is not None:
            try:
                return self._opener(self._url, body, self.timeout)
            except Exception as exc:
                raise RpcError("RPC_TRANSPORT_FAILED", self.mask(repr(exc))) from None
        request = urllib.request.Request(
            self._url, data=body,
            headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read() or b""
        except Exception as exc:  # transport: DNS, TLS, timeout, reset
            raise RpcError("RPC_TRANSPORT_FAILED", self.mask(repr(exc))) from None

    # --------------------------------------------------------------- call
    def call(self, method: str, params: list | None = None):
        """One request. One attempt. No retry, ever."""
        if method not in ALLOWED_METHODS:
            raise RpcError("RPC_METHOD_NOT_ALLOWED", method)
        params = list(params or [])
        self.ledger.reserve(method)
        units = archive_units(_queried_block(method, params), self.known_head)
        request_id = self.ledger.attempts + 1
        payload = json.dumps({"jsonrpc": "2.0", "id": request_id,
                              "method": method, "params": params}).encode()
        try:
            status, raw = self._post(payload)
        except RpcError as exc:
            self.ledger.record(method, units=units, error=exc.code)
            raise
        if status == 429:
            self.ledger.record(method, units=units, error="RPC_QUOTA_STOP")
            self.ledger.halt("HTTP_429")
            raise BudgetStop("RPC_QUOTA_STOP", "HTTP_429")
        if status in (413, 414):
            # "payload / URI too large": the same per-request refusal as a
            # range message, and equally curable by asking for less.
            self.ledger.record(method, units=units, error=RANGE_TOO_LARGE)
            raise RpcError(RANGE_TOO_LARGE, f"HTTP_{status}")
        if status != 200:
            code = f"RPC_HTTP_{status}"
            self.ledger.record(method, units=units, error=code)
            raise RpcError(code)
        if len(raw) > 20_000_000:
            self.ledger.record(method, units=units, error="RPC_INVALID_RESPONSE")
            raise RpcError("RPC_INVALID_RESPONSE", "body too large")
        try:
            envelope = json.loads(raw)
        except ValueError:
            self.ledger.record(method, units=units, error="RPC_INVALID_RESPONSE")
            raise RpcError("RPC_INVALID_RESPONSE") from None
        if (not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0"
                or envelope.get("id") != request_id):
            self.ledger.record(method, units=units, error="RPC_INVALID_ENVELOPE")
            raise RpcError("RPC_INVALID_ENVELOPE")
        error = envelope.get("error")
        if error is not None:
            message = str(error.get("message", "")) if isinstance(error, dict) else str(error)
            code = error.get("code") if isinstance(error, dict) else None
            kind = classify_provider_error(message)
            if kind == "QUOTA":
                # Keep the provider's own words, masked. Without them a result
                # limit ("logs matched by this request exceed the limit") and a
                # spent quota are the same string to us, and the wave would
                # stop for the wrong reason with nothing to read afterwards.
                detail = f"PROVIDER_QUOTA code={code} message={self.mask(message)}"
                self.ledger.record(method, units=units, error="RPC_QUOTA_STOP")
                self.ledger.halt(detail)
                raise BudgetStop("RPC_QUOTA_STOP", detail)
            if kind == "RANGE":
                # Curable by asking for less. Counted, never halted.
                self.ledger.record(method, units=units, error=RANGE_TOO_LARGE)
                raise RpcError(RANGE_TOO_LARGE, self.mask(message))
            coded = f"RPC_ERROR_{code}"
            self.ledger.record(method, units=units, error=coded)
            raise RpcError(coded, self.mask(message))
        if "result" not in envelope:
            self.ledger.record(method, units=units, error="RPC_MISSING_RESULT")
            raise RpcError("RPC_MISSING_RESULT")
        self.ledger.record(method, units=units)
        return envelope["result"]

    # ------------------------------------------------------- typed helpers
    def chain_id(self) -> int:
        return int(str(self.call("eth_chainId", [])), 16)

    def block_number(self) -> int:
        head = int(str(self.call("eth_blockNumber", [])), 16)
        self.known_head = head
        return head

    def block(self, tag) -> dict:
        """``tag`` is an int, or one of ``latest`` / ``safe`` / ``finalized``."""
        param = _hexnum(tag) if isinstance(tag, int) else str(tag)
        header = self.call("eth_getBlockByNumber", [param, False])
        if not isinstance(header, dict) or "hash" not in header:
            raise RpcError("RPC_INVALID_BLOCK", str(tag))
        out = {"number": header["number"], "hash": header["hash"],
               "parentHash": header["parentHash"], "timestamp": header["timestamp"]}
        if tag == "latest":
            self.known_head = int(str(out["number"]), 16)
        return out

    def code(self, address: str, block: int | str = "latest") -> str:
        param = _hexnum(block) if isinstance(block, int) else str(block)
        return str(self.call("eth_getCode", [address, param]))

    def logs(self, addresses: list[str], from_block: int, to_block: int,
             topics: list | None = None) -> list[dict]:
        """One filtered ``eth_getLogs``, validated against the filter it asked for.

        The donor refuses a response that steps outside the filter
        (``RPC_LOG_OUTSIDE_FILTER``); so does this. A ``removed: true`` log is
        **not** refused here — the collector needs to see it to orphan what it
        affects (addendum 6) — which is the one deliberate difference from the
        donor's client, whose datasets are snapshots rather than a live cursor.
        """
        if not addresses:
            return []
        wanted = {a.lower() for a in addresses}
        criteria = {"address": [a.lower() for a in addresses],
                    "fromBlock": _hexnum(from_block), "toBlock": _hexnum(to_block)}
        if topics:
            criteria["topics"] = topics
        out = self.call("eth_getLogs", [criteria])
        if not isinstance(out, list):
            raise RpcError("RPC_INVALID_RESPONSE", "eth_getLogs")
        if len(out) > 20_000:
            raise RpcError("RPC_LOG_RESPONSE_TOO_LARGE", str(len(out)))
        for log in out:
            number = int(str(log["blockNumber"]), 16)
            if (str(log["address"]).lower() not in wanted
                    or number < from_block or number > to_block):
                raise RpcError("RPC_LOG_OUTSIDE_FILTER")
            if topics:
                for i, topic in enumerate(topics):
                    if topic is None:
                        continue
                    got = log["topics"][i] if i < len(log["topics"]) else None
                    if str(got).lower() != str(topic).lower():
                        raise RpcError("RPC_LOG_OUTSIDE_FILTER")
        return out


def keccak256(data: bytes) -> bytes:
    """keccak-256, imported here rather than at module scope.

    ``pycryptodome`` is declared in the optional ``chain`` group of
    ``pyproject.toml`` and nothing at import time needs it, so the main
    dependency set stays numpy/scipy/pandas/pyarrow (addendum 4).
    """
    from Crypto.Hash import keccak  # noqa: PLC0415 - deliberate, see docstring

    return keccak.new(digest_bits=256, data=bytes(data)).digest()


def keccak256_hex(data: bytes) -> str:
    return "0x" + keccak256(data).hex()
