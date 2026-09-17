# Holder access

The main broadcast has a persistent account button above the fold. The account
panel separates connection, signed ownership verification, and immutable bag
eligibility. Reading the broadcast or allocation history needs no signature.
Voting/chat use the existing signed Bag API; claims use the existing signed
canonical allocation API and confirmed payout receipts.

One session supplies the account to all three. Account/network changes clear
verification and close the previous account's claims. In-flight responses and
signatures cannot reopen or authorize the previous account. Reload restores only
an already-authorized browser account, without requesting a signature or
restoring verified status. Disconnect clears this site's session/preference.
It does not revoke extension permissions on the user's behalf.

Detected wallets use [EIP-6963](https://eips.ethereum.org/EIPS/eip-6963), with a
legacy injected-provider fallback. Provider metadata is untrusted text; bounded
image icons render as images, never executable SVG markup. Connection, signing,
cancellation, wrong network, missing wallet, and service-unavailable states have
explicit recovery actions. The dialog has keyboard focus, Escape, and layouts
checked at 1440x900, 390x844, and 430px. Reduced-motion settings are preserved.

## Network and QR

The switch/add action requests chain 4663 (0x1237) with the official public
[Robinhood Chain wallet parameters](https://docs.robinhood.com/chain/connecting/).
It never exposes or replaces the worker's private RPC. Only explicit user
connection/signature/network actions call the provider; the holder frontend
never requests an approval or eth_sendTransaction.

Optional QR pairing uses the self-hosted, lazy-loaded Reown EthereumProvider
2.25.0 SDK. A real public Project ID is required by
[Reown](https://docs.reown.com/advanced/providers/ethereum):

```sh
WALLETCONNECT_PROJECT_ID=<32-hex-public-project-id>
```

Configure the final site origin in the Reown project allowlist, add the ID to
the viewer's existing environment file, then restart only the viewer:

```sh
the user service restart the-viewer-user-unit
curl -sS http://localhost:8797/api/wallet-config
```

The endpoint exposes only an allowlisted public configuration. Missing/invalid
IDs disable QR. TEST HOLDERS and isolated fixture deployments disable QR even
with an ID; they never recruit a real wallet to represent fake holder ownership.
Mobile users can also open the site inside an EIP-1193 wallet browser. No working
Project ID was supplied for this release: real QR pairing remains unvalidated
and must be checked with a real wallet after configuration. Do not describe it
as already active.

The SDK is fetched only after choosing WalletConnect. CSP adds its explicit
relay/RPC/verification origins only when QR is enabled; there is no wildcard
network permission, CDN script, or private signer value. SDK telemetry is off.
The connection requests only account, typed-message, and network methods.

To rebuild the pinned bundle:

```sh
cd tools/wallet
npm ci --ignore-scripts --no-audit --no-fund
npm run build
```

## Current PAPER + TEST HOLDERS deployment

The header says TEST HOLDER. The selector provides only the isolated test
identity; the installed browser wallet stays untouched. The banner chooses the
test crew. Snapshot eligibility is still server-derived for the actual main
worker's PAPER bag. There are no real funded claims for these holders.

No brain, entry/exit policy, snapshot, voting weight, accounting, payout signing,
or trading service was changed by this UI pass. Only the viewer needs a restart.
The subsequent viewer-only SQLite deadlock fix and its verified runtime are
documented in viewer-recovery notes.

## Focused verification

```sh
.venv/bin/python -m pytest tests/bags tests/payout tests/strong_v1/test_api.py tests/strong_v1/test_wallet_config.py -ra
data/runtime/bag-room-env/bin/python tools/wallet/browser.py --output /tmp/fly-holder-access-qa
data/runtime/bag-room-env/bin/python tools/payout/demo.py --output /tmp/fly-holder-payout-qa
```

Browser fixtures use actual signed backend transitions, multiple mock providers,
network correction, canceled signatures, account changes during signing and
claims loading, passive reload, disconnect, keyboard navigation, and mobile.
The payout demo uses local Anvil receipts and test funds, not public transactions.
Evidence and installed-site screenshots are under output/holder-access/.
