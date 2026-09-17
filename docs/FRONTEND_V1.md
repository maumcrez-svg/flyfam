# Spectator frontend — local review build

The frontend in `spectacle/static` now consumes the actual continuous paper worker.
The local migration and browser checks are recorded in `live-activation notes`.
The old P1 adapter `spectacle/serve.py` does not supply this frontend's contract.

## Open / operate locally

Viewer: `http://localhost:8797/`.
Health: `http://localhost:8797/api/health`.
The installed `the-viewer-user-unit` reads
`./data/pons/live/product.sqlite3` and serves the
persistent release at `data/runtime/strong-v1/spectacle/static`.

```sh
the user service status the-pons-user-unit the-viewer-user-unit
the user service restart the-viewer-user-unit
the service log -u the-viewer-user-unit -f
```

The previous historical rehearsal command must not be started on occupied port
8797. Offline rehearsals can use another port. Boot persistence is not enabled.

## Existing presentation

SNIFFING shows actual presented candidates, server ranks and raw Hz; a new
completed round may update arrows only for shared candidates under the same
score definition. Canonical OVERTAKE moments supply the callout. Final aggregate
measurements are never animated as imaginary intra-round computation. The
sensory inspector shows raw input features with units and no probability bars.

PICK, OPEN, CLOSE and CREDIT have distinct takeovers. Ordinary marks update the
broadcast without a siren. The position shows canonical net return and net ETH
independently, modeled exit value, peak, drawdown, observed chart and fixed-policy
countdown. Expiry waits for a recorded close. Missing observations form gaps.
No browser-derived authoritative PnL or independent career aggregation exists.

The timeline, permanent career, separate FLY_REJECTED/FILTERED_OUT receipts and
fixed follow-up windows use server projections. No price rise is described as
executable paper profit when the modeled quote is unavailable. Names, tickers and logo thumbnails resolve from the local node into a separate
bounded identity cache. The contract stays below the name, including duplicate
tickers. Missing icons have an explicit initials fallback; metadata is escaped
or inserted as text. See `docs/CHARACTER_AND_IDENTITY.md`.

Replay routes `/episode/<run:id>` reconstruct the recorded watchlist and pick,
then request sequence-bounded frames. Future close, credit, peak and career do
not appear early. Replay is visibly labeled, and polling continues in the
background. The current career is hidden until the historical close snapshot
becomes available. Back to Live reconciles the latest snapshot.

Sound is opt-in and respects browser audio activation and reduced motion.
Following a live position stores its ID locally and requests notification
permission only after Follow. CLOSE may notify an open/backgrounded page; no
closed-browser push infrastructure is claimed. On return the canonical episode
result is available. While Away uses the backend summary after the last local
consumed canonical sequence. Story and canonical sequence domains stay separate.

The mascot now uses the repaired Meshy GLB in `assets/the-fly.glb`, rendered by
locally vendored Three.js 0.180.0. The two lower forward legs have independent
body/upper/lower/foot chains; all six limbs can be inspected at
`http://localhost:8797/rig-inspector.html`. The user's original file is unchanged.
See `art/meshy/RIG_REVIEW.md` for provenance, repair and numerical pose evidence.

The same character appears in the chamber, major takeovers, career portrait and
share card. One canvas is moved into takeovers, so no extra renderer is created.
Head, antenna, wing and limb poses are **presentation animation**, never measured
motor activity. The authored controller blends poses with time-based springs, plants all four
supporting feet with two-bone inverse kinematics, staggers the gaze/antennae/arms
and uses occasional wing flicks. Reward gathers then opens; punishment settles
into a lowered pose. The motion studio previews each reaction and the full loop.
No animation clips are embedded in the GLB. The schematic neural
field continues using recorded population rates only. Both eyes remain open.

Rendering is capped at 30 fps and DPR 1.5; hidden/offscreen views do not draw,
and reduced-motion or stale idle views render only when their state changes.
A portrait captured from this same model remains visible while loading or when
WebGL is unavailable. A lost graphics context restores the model and generated
lighting before hiding that portrait. The loader only signals ready after a real
mesh draw. All Three.js code and model textures are local; no CDN is required.

The planned economics section is explicitly NOT LIVE; no distributions, fees
received, APR or token contract are invented.

## Share artifacts

Completed episodes render a 1200×630 browser canvas receipt with canonical PAPER
result, entry/exit times, peak, CREDIT and episode URL. Download PNG, native Share
when supported and copy-link fallback are implemented.

The isolated renderer reads the same episode route, records its presentation,
and uses ffmpeg in a subprocess (two encoding threads). It never enters the
worker process and cannot trigger trading. Outputs are 12-second, 30fps MP4
in 1280×720 and 720×1280, plus the PNG and provenance manifest.

```sh
python tools/render-spectacle-share.py --episode pons-live:666003138
python tools/render-spectacle-share.py --watch
```

The first command rendered the real captured episode; the optional serial
watcher discovers completed episodes and skips manifests already present. It is
not currently installed as a background service. Outputs live under
`spectacle/static/shares/` (generated, ignored by Git). GET
`/api/episode/<id>/artifacts` only lists existing rooted assets. It never starts
rendering. Available landscape/portrait downloads appear in the share dialog.

## Analytics

First-party local event schema: `{event, ts, mode, episode_id?}`. Names include
viewer_open, live_view_started, watchlist_seen, pick_seen, position_open_seen,
follow_position, close_seen, episode_replay_opened, ones_that_got_away_opened,
share_card_created, share_clicked, return_after_follow. A maximum of 300 events
is kept under `fly.v2.analytics` in the viewer browser. No wallet, account or
cross-site identifier is collected. Storage denial is non-fatal.
**This is local instrumentation, not a central retention analytics collector.**

## Rendered QA

```sh
python tests/browser/verify_spectacle_v2.py
python tests/browser/verify_fly_rig.py
node tests/browser/verify_fly_motion.mjs
python tests/browser/verify_character_identity.py
```

Chromium and WebKit: state flow, real rank changes, raw accounting display,
reconnect deduplication, follow permissions, close/credit, replay, historical
career, separate misses, while-away, share canvas, unsafe token metadata and
mobile overflow at 390/430px. Desktop viewport 1440×900. Synthetic screenshots
are explicitly labeled UI FIXTURE; they are not actual Fly trades. Real history
also exercised replay and card generation without page errors.

Local screenshots and JSON evidence: `art/qa/`. `browser-report.json` records
both browser runs; `final-browser-check.json` records the mobile timer, downloads
and measured review-page overhead. These checks do not prove production viewer
capacity, whole-worker memory bounds or a live-service migration.

The GLB-specific browser check verifies all 46 joints, actual nonempty portrait
pixels, each leg/arm pose, forced GPU context recovery, reduced motion, stale
idle rendering and same-character fallback at mobile width. Results are in
`art/qa/rig-browser-report.json`; both Chromium and WebKit passed. The full
spectator flow was rerun with the 3D model, including real-history replay/share.
