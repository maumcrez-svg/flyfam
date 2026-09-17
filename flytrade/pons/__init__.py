"""Pons (Robinhood Chain, chain id 4663) chain access for the D10 wave.

Everything that talks to a blockchain lives in this package and nowhere else.
The rest of ``flytrade`` never imports it, and the observer is forbidden from
importing :mod:`flytrade.pons.rpc` at all (docs/SPEC.md D10 addendum 13).

The package is deliberately thin: standard-library HTTP, a method allowlist
that has no signing or broadcast member, a persisted request ledger, hand
decoding of a handful of static-layout events, and an integer-exact port of
the PONS v2 bonding-curve quote. No ``web3``, no ``eth-abi``, no RPC provider
SDK. ``keccak-256`` comes from ``pycryptodome`` and is imported inside the two
functions that need it, so importing this package does not require the
optional ``chain`` dependency group (addendum 4).
"""

CHAIN_ID = 4663
VENUE = "PONS"
PONS_VERSION = "flytrade-pons-1"
