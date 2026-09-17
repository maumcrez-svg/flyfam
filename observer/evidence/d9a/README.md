# D9(a) — captured browser evidence

Captured with the machine's headless Chromium (`/snap/bin/chromium`,
`--headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=W,H
--virtual-time-budget=9000 --screenshot=...`) against the local observer at
`http://localhost:8791/`, using the page's own deep link
`?run=&branch=&seq=&record=1&detail=1`. Each PNG was then quantised with
`pngquant --quality=70-95` to stay under the 300 KB ceiling of addendum 11.
No Playwright package was installed.

| file | viewport | what it shows |
|---|---|---|
| `01-senses-and-neural-1440x900.png` | 1440×900 | `d7-001/learned` line 38, the first DECISION of the LEARNING partition. Recorded features → recorded glomerular rates, the schematic with its Kenyon-cell block and the two MBON discs, the eight replicate marks, a decoded WAIT-side reading |
| `02-decision-open-position-1440x900.png` | 1440×900 | line 49: a decision taken while episode 25000000 is open — the position panel carries the entry fill, the market minutes held and the remaining maximum policy horizon |
| `03-settled-and-learning-1440x900.png` | 1440×900 | line 88, the `LEARNING` event of episode 25000000: net **+2.1353**, "reward applied", and the dashed overlay reading *reward · 3,346 synapses depressed* |
| `04-frozen-no-learning-1440x900.png` | 1440×900 | `d7-001/frozen_trained` line 5653: phase FROZEN · learning off, header counts **0 learning**, result **−1.2957** badged *result — learning frozen*, and no plasticity overlay |
| `05-no-response-1440x900.png` | 1440×900 | line 352: `NO_RESPONSE` — approach and avoid both 0.000 Hz, 8/8 silent replicates, all eight marks dim, "an absence of activity is recorded as an absence, never as a choice to wait" — while a position is open with 85 of 90 minutes of maximum policy horizon left |
| `06-run-selector-hist-001-1440x900.png` | 1440×900 | `hist-001/learned` selected by identity, at line 49 — an outcome closed by `POLICY_CLOSE` (a state `d7-001` never reached), H = 8 read from `config.execution.horizon_minutes`, and the **missing-optional-telemetry** case on real data: a D5/D6 log carries no `observation`, `stimulus` or `readout` sub-object, so bar close, the feature bars, the glomerular rates, the Kenyon-cell fields and the replicate marks all read *unavailable* rather than zero |
| `07-experiment-record-1440x900.png` | 1440×900 | the experiment-record drawer behind its explicit action: D7's and D8's wording, the target mismatch, the fixed-hold caveat, `registered-horizon-artifact`, the probe panel and the context summary (unsealed here only because the cursor is at the end of the branch) |
| `08-event-detail-1440x900.png` | 1440×900 | the event-detail drawer at line 88: the canonical `LEARNING` event unchanged, and the linked decision (line 85), outcome (line 86) and learning (line 88) — the fill reads *not reached at this cursor*, because the position had already closed |
| `09-senses-and-neural-390x844.png` | 390×844 | the same line 38 in the narrow layout: one column, the mode strip unpinned |
| `10-settled-and-learning-390x844.png` | 390×844 | line 88 in the narrow layout |
