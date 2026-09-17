# Flytrade spectacle

A local, read-only product surface for the running frozen PONS paper trader.
Open **http://localhost:8796** while the viewer server is running.

```sh
./.venv/bin/python spectacle/serve.py \
  --feed-dir ./data/pons/live --port 8796
```

The server binds loopback only. No package installation, build, RPC access,
wallet integration, producer restart, or external hosting is involved. The
front uses browser-native JavaScript, CSS and an original animated SVG fly.
Stop this viewer with Ctrl-C; the trader is a separate process.

## The experience

- SNIFF: candidates orbit the fly, carrying actual admission outcomes. While
  holding, these are clearly marked earlier scents and the held token remains
  highlighted. No new sniffing is implied on holding ticks.
- PICK: a candidate choice takes the stage with the decoded action and centred
  valence in Hz. A BUY response is never counted as a paper entry by itself.
- OPEN/MARK: a real OPEN controls the position. The chart draws observed net
  position marks, not invented candles or interpolated market prices. The
  timer can reach zero without a CLOSE: it says awaiting settlement.
- CLOSE/CREDIT: reward, punishment or neutral impact, with MEMORY DISABLED.
  The closed episode remains replayable; the arena returns to the current
  position or sniffing. Optional audio starts only after the user enables it.

The real feed currently includes an entry-associated PICK marked HELD just
before OPEN (for example the first episode, seq 2 then 3). Presentation links
that PICK to the actual same-tick, same-token OPEN. The source context is not
rewritten, and subsequent held-token reactions do not create entry animations.

The contract has no token symbols/names. Addresses are abbreviated and can be
copied in full; decorative address-derived glyphs are not token logos. No
symbols, confidence percentages, price history or reasons for winning are
fabricated. Admission filtering and neural output are presented separately.

## Feed access and replay

Only `docs/SPECTACLE_FEED.md`, `state.json` and the public daily
`events-YYYY-MM-DD.jsonl` journals define this viewer. The HTTP adapter never
reads the chain store, internal journal, keys, or brain. It never writes to the
feed directory. The live service and scientific observer stay independent.

`/api/feed?after=N` returns atomic state plus public event deltas and the most
recent non-holding SNIFF. It respects the state's committed sequence, retries
an incomplete journal tail, and indicates sequence gaps. Polling is 2.5 s;
source cadence remains 30 s. Old state, stopped source, missing feed and
connection failure are visible. Stale observations are not animated as live.

`/api/replay?episode=N` returns actual events from the matching entry tick
through CREDIT. Replay is explicitly marked, time compressed, cancellable and
never changes the trader. Counts for sniffing and picks refer to the replay;
account PnL is the recorded account at that time. Past live events are not
replayed as new events on initial page load or reconnection with a sequence gap.

The adapter's cold scan is capped at the final 16 MiB of each of the latest two
UTC day files, and its event cache at 12,000 records. An older episode whose
complete OPEN-to-CREDIT sequence is absent returns a visible unavailable
message; the UI never fabricates a partial replay. This is a local viewer,
not a public production deployment or an unlimited archive service.

## Verification

```sh
./.venv/bin/python -m pytest spectacle/tests/test_feed.py -q
python spectacle/tests/browser_check.py
```

The three adapter tests check atomic-state sequence bounds, partial-line retry,
midnight journals, real-choice/held-response replay order, unavailable history,
journal gaps, and no writes. Browser checks run Chromium and WebKit at 1440×1000 and 390×844:
actual reward and punishment episode replays through all four acts, live return,
activity/rejection tabs, story dialog, sound toggle, stale/offline handling,
no horizontal overflow, and no page JavaScript errors. Screenshots and results
are in `spectacle/evidence/`. Browser checks require a running local viewer and
at least one recorded reward and punishment within its available window.
