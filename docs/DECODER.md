# Decoder — pre-registration

**This file and `flytrade/decoder.py` are committed alone, before any
execution, accounting or PnL code exists in the repository.** The SHA ordering
in `git log` is the evidence that the readout, its sign, its aggregation, its
threshold and its tie rule were fixed before any trading outcome had been seen.
The same discipline `experiments/conditioning/PROTOCOL.md` was committed under
(`b9655ea`, alone, before `run.py` existed).

Version `flytrade-action-1`. Canonical amendment §3, Fable addenda 3 and 4.

What may still change, and when it stops being allowed to:

* the **sign convention** may be corrected once, using the §4 conditioning
  demonstrations, and is frozen at the commit that precedes §6;
* everything else — populations, aggregation, θ, the four statuses, the tie
  rule — is frozen here;
* **nothing** in this file is touched after any PnL has been observed, and a
  later wave that wants to change it starts by saying so in `the session log`.

## 1. What this decoder is not

There is no trading strategy in it, no classifier, no LLM, no learned policy
and no model of a market. It compares two measured firing rates against a
threshold expressed in units of their own measurement noise. Every
market-dependent quantity that reaches it arrived through the ORN → uPN →
Kenyon-cell → MBON path documented in `docs/ENCODER.md`.

It contains no free parameter that was chosen by looking at returns. The two
constants it carries are measurements with a stated provenance, taken before
any position was ever opened.

## 2. The readout populations

Both are taken from the **corrected** DAN → MBON compartment map in
`flytrade/mushroom.py` — `D[mbon][:, dan].sum(axis=1)`, dopaminergic synapses
each MBON *receives* — and both are restricted to the MBONs the valence
literature attributes a behavioural direction to, `MBON01`–`MBON15`
(`flytrade.populations.mbon_attributed`).

| population | compartment (measured) | MBON types on MaleCNS v1.0 | neurons |
|---|---|---|--:|
| `avoid` | PAM-innervated | MBON01, 02, 03, 04, 05, 06, 07, 09, 10 | **29** |
| `approach` | PPL1-innervated | MBON11, 12, 13, 14, 15 | **16** |

The other 52 MBONs are **excluded, not guessed**: `MBON16`–`MBON35` and the
three `-like` types have no compartment-plus-valence attribution we are willing
to stand behind (`docs/POPULATIONS.md` ambiguities 1 and 5). `readout_populations`
additionally drops any MBON the compartment map flags as `ambiguous` — thin or
near-tied dopaminergic evidence. On MaleCNS v1.0 that set is empty for
MBON01–15, so the counts above are 29 and 16; the filter is in the code because
the next dataset may not be so tidy.

Aggregation is the unweighted mean of the per-neuron firing rate over the 20 ms
presentation window. No neuron carries a hand-set weight.

## 3. The three-column table

Amendment §3 requires modulation compartment, supported functional
interpretation, and our action-mapping convention to be kept apart. They are:

| (a) modulation compartment, **measured** | (b) literature-attributed valence, **attributed not measured** | (c) our action-mapping convention, **ours** |
|---|---|---|
| PAM-innervated (`avoid`, 29 neurons). PAM neurons signal reward. | Activating these MBONs promotes **avoidance**. Aso, Sitaraman, Ichinose et al. 2014, *eLife* 3:e04580; reviewed in Owald & Waddell 2015, *Curr Opin Neurobiol* 35:178. | Their firing pushes the readout **away from BUY**. |
| PPL1-innervated (`approach`, 16 neurons). PPL1 neurons signal punishment. | Activating these MBONs promotes **approach**. Same sources; the canonical case is MBON-γ1pedc>α/β (MBON11), whose depression after punishment is what reduces approach. | Their firing pushes the readout **toward BUY**. |

Three things to be explicit about.

**The direction is the opposite of the naive reading**, which the amendment
warns against by name. "PAM = reward = BUY neurons" is wrong in the literature:
the reward-compartment MBONs drive avoidance, and reward *depresses* them,
which is how a rewarded odour becomes attractive. Our convention follows the
attributed direction, not the convenient one.

**Three layers, and they are not the same claim** (D4 §6, Fable addendum 11).

*(a) Observed anatomy, measured.* On MaleCNS v1.0, read through
`graph_mod.npz`, 29 of the attributed MBONs receive more dopaminergic synapses
from PAM than from PPL1 and 16 receive more from PPL1 than from PAM. That is a
measurement on this dataset and it is all that is measured here.

*(b) Literature interpretation, attributed.* That activating the first group
promotes avoidance and the second approach is read from the sources in the
table above. It assumes the numbering here is the hemibrain numbering
(`docs/POPULATIONS.md` ambiguity 1) and that a cell type's reported valence
transfers to this dataset's homologue. Neither is verified by us.

*(c) Our convention, ours.* `V = PPL1-side − PAM-side`. It is a declared
mapping from (b) to an action axis, chosen and labelled as a choice.

**What the plasticity adds is a consistency check, not a proof.** The mushroom
body can only depress (`docs/ARCHITECTURE.md`, constraint 3). Under this
convention a profitable outcome routes dopamine to PAM, depresses `avoid`,
raises V, and the same context decodes closer to BUY; the opposite convention
would move the readout the other way under the same reinforcement. That makes
the two conventions *distinguishable by their behaviour*, which is a reason to
prefer this one. It is not evidence that grouping MBONs by dopaminergic
innervation establishes a universal behavioural valence. An earlier version of
this section called it "the only direction consistent with depression-only
plasticity"; that was too strong and is corrected here. The decoder itself is
unchanged.

**The MBON numbering is assumed, not verified**, to be the hemibrain numbering
(`docs/POPULATIONS.md` ambiguity 1). If it is wrong, (b) is wrong and (c) with
it. (a) is unaffected: it is measured from this dataset's own connectivity.

## 4. The rule

```
V_raw = mean rate(approach) - mean rate(avoid)              Hz
V     = V_raw - BASELINE_HZ                                 Hz

1.  INVALID_STATE   if kc_fraction > 0.25
                    or any read neuron >= 0.95 * 454.5 Hz
2.  NO_RESPONSE     if approach == 0 and avoid == 0
3.  BUY             if V > +THETA_HZ
4.  SELL            if V < -THETA_HZ
5.  WAIT            otherwise
```

Order matters and is part of the specification: saturation is checked before
silence, and silence before the margin, so that a silent readout can never be
reported as a decision to wait.

### The two constants

| constant | value | provenance |
|---|--:|---|
| `BASELINE_HZ` | **-2.303341 Hz** | mean of `V_raw` at the neutral reference stimulus (`u = 0`, every feature at its own trailing median), gain 0.10, unlearned weights, declared operating range, 8 declared seeds. `experiments/phase_one/encoder_range.json`, `neutral_reference.attributed_diff_hz_mean`. |
| `BASELINE_SD_HZ` | **3.241438 Hz** | seed-to-seed SD of the same quantity, same run, `attributed_diff_hz_sd`. |
| `THETA_HZ` | **3.241438 Hz** = 1.0 × `BASELINE_SD_HZ` | Fable addendum 4: the margin is stated in units of the measured baseline SD, never in PnL terms. |

The fly's readout is not balanced at rest — the 29 PAM-innervated MBONs fire
faster than the 16 PPL1-innervated ones at the neutral reference, 5.819 Hz
against 3.516 Hz — so `V_raw` has an offset, and `BASELINE_HZ` removes it.
It is a measured property of the circuit at the declared operating point, not a
knob. Both constants were measured **before** this file existed, by the §1
commit, with no position ever opened.

θ = 1 SD is deliberately wide. At this operating point the seed-to-seed SD of
the readout is comparable to its signal (`docs/ENCODER.md` §4), so a narrower
margin would be reporting noise as decisions. The consequence is that WAIT is
the common outcome, and that is the honest result rather than a defect.

## 5. The four statuses

`Action` gains no members (Fable addendum 4). Every record carries a separate
`readout_status`:

| status | meaning | action emitted |
|---|---|---|
| `VALID` | a real readout inside the declared operating range | `BUY` / `SELL` / `WAIT` |
| `NO_RESPONSE` | both readout populations silent — nothing was measured | `NO_RESPONSE` |
| `INVALID_STATE` | saturated, or Kenyon recruitment outside the declared range | `NO_RESPONSE` |
| `POLICY_REJECT` | the decoder produced a valid action and the **execution policy** refused it | the decoded action is kept in the record |

Only `VALID` + `WAIT` is a neural choice to wait. The other three must never be
presented as one. A `DecisionRecord` keeps the decoded action and the executed
action separately, so a `POLICY_REJECT` never erases what the fly actually
decoded.

## 6. Selection and ties

The round score for a candidate is its centred valence `V`; the selected
candidate is `argmax V`; **ties resolve to the lowest stable id**
(`flytrade/runner.py`), which is assigned at universe registration and is
independent of symbol spelling and of list position. A candidate whose status
is not `VALID` returns no score and cannot win a round.

No market feature breaks a tie, and no market feature enters the score.

## 7. Action semantics

`BUY` / `SELL` / `WAIT` are preserved as the product-facing action space.
Against the offline execution fixture they are inventory-aware and long-only
(amendment §3):

* `BUY` opens or increases permitted long exposure;
* `SELL` reduces existing exposure;
* `WAIT` leaves exposure unchanged.

`SELL` is never an unimplemented short. A mechanical horizon expiry is
`POLICY_CLOSE` and is not a neural `SELL`; the distinction lives in
`docs/EXECUTION.md` and in the record, not here.

---

## 8. Amendment — the k = 8 readout (D4, 2026-09-11)

Version `flytrade-readout-1`, alongside decoder `flytrade-action-1`. This is a
**versioned amendment to the normalisation**, recorded as one rather than
described as a pipeline that is numerically unchanged — because it is not.

What changed: how many presentations reach the decoder, and therefore the
dispersion the WAIT margin is stated in.

What did **not** change: `V = mean(approach) − mean(avoid) − BASELINE`, the
populations (29 `avoid` / 16 `approach`), the sign convention of §3, the rule
order of §4, the four statuses of §5, the tie rule of §6, the action semantics
of §7, the dimensionless margin coefficient `THETA_SD = 1.0`, the gain 0.10,
the 20 ms window and the encoder's declared input range.

### The aggregate

Eight presentations of one candidate, each from an equivalent copy of the
round's transient snapshot, on the seed schedule `flytrade/readout.py` §2
declares. Their **mean per-neuron rates** are decoded **once**. There is no
majority vote over eight labels and no strongest-replicate selection.

The aggregate's Kenyon fraction and peak rate are **maxima** over the eight, so
the rule order of §4 — saturation, then silence, then the margin — yields the
status rules the amendment's Fable addendum 4 fixes: `INVALID_STATE` if *any*
replicate is saturated or over-recruited, `NO_RESPONSE` only if *every*
replicate was silent, otherwise `VALID`. A silent replicate inside an active
batch contributes its zeros and is never discarded.

### The two constants, by k

| constant | k = 1 | k = 8 |
|---|--:|--:|
| `BASELINE_HZ` | **−2.303341 Hz** | **−0.844390 Hz** |
| `BASELINE_SD_HZ` | **3.241438 Hz** | **0.911719 Hz** |
| `THETA_HZ` = 1.0 × SD | **3.241438 Hz** | **0.911719 Hz** |
| N | 8 seeds | 64 batches |
| distribution | `V_raw` of one presentation | `V_raw` of one **batch** aggregate |

Both are measured at the same neutral reference (`u = 0`), the same unlearned
reference brain state, the same gain and window. The k = 8 pair was measured by
`experiments/k8_readout/baseline.py` under the procedure pre-registered alone
at commit `4b8e082`, and the artifact with its provenance — graph sha256, state
digest, seed namespace, N, commit, and all 64 samples — is
`experiments/k8_readout/baseline_k8.json`.

The divisor is the **sample standard deviation of the batch distribution**
(ddof = 1), never the standard error of its mean. Degenerate dispersion is an
explicit stop, not an epsilon: see `readout.DegenerateBaseline`.

The k = 1 constants in §4 are **kept**, unmodified, and are the constants of
the k = 1 regression mode.

### What the ratio says

SD₈ / SD₁ = **0.314** measured on the same 64-batch schedule (0.281 against the
Phase One 8-seed SD). The independent-replicate expectation is 1/√8 ≈ 0.354.
The measured ratio is **compatible with sampling variation**, and the results
do not establish another cause: an SD from 64 draws carries ≈ 9 % relative
error and the ratio of two such SDs ≈ 13 %, so 0.314 sits about 11 % from the
expectation. It is reported, not fixed, and it is not a finding.

The two k = 1 baseline offsets disagree — −2.303 Hz over 8 seeds against
−0.803 Hz over 64 draws of this schedule — and that is a sample-size fact, not
a change in the circuit: the standard error of the Phase One estimate is
3.241/√8 = 1.15 Hz, so the two are about 1.3 standard errors apart. The Phase
One constant is **not** retrofitted. It stays exactly where `f63825b` put it,
because it is what the k = 1 mode was pre-registered with.

## 9. D5 — the margin, frozen

The owner's D5 answer keeps the rule exactly as §8 measured it. Nothing in
this section changes a number; it fixes what the number **means** and what may
never be done to it.

### What θ is

θ is an **action-decoding rule**. It says how far the centred valence `V` has
to sit from the neutral reference before the readout is called a choice rather
than a reading. It is expressed in units of the measured dispersion of the same
estimator's own baseline, so that a readout which seed noise alone could
plausibly have produced is not turned into an order.

θ is **not a probability of financial success**, not a confidence that a trade
will work, not a forecast, and not a risk control. It contains no market
quantity, no outcome, and no PnL. A `BUY` at `V = 1.2 Hz` is a statement about
45 MBON firing rates over 20 ms, and about nothing else.

### What is frozen

| frozen | value | where |
|---|---|---|
| dimensionless coefficient | `THETA_SD = 1.0` | `flytrade/decoder.py` |
| k | 8 | `flytrade/readout.py` |
| `BASELINE_HZ₈` | −0.844389816810345 | `baseline_k8.json`, loaded exactly |
| `BASELINE_SD_HZ₈` | 0.9117185769796697 | `baseline_k8.json`, loaded exactly |
| θ₈ | 1.0 × SD₈ = 0.9117185769796697 Hz | derived, never typed |
| formula and sign | `V = mean(approach) − mean(avoid) − BASELINE` | §2–§4 |

The stored artifact is the source. A run loads
`experiments/k8_readout/baseline_k8.json` and uses its full-precision values;
a number transcribed from a report, rounded to four decimals, or re-derived
from a printed table is not the baseline and is refused
(`tests/k8_readout/test_baseline_artifact.py`).

The baseline is **not** recalibrated, and the coefficient is **not** retuned,
using historical returns, trade frequency, or preferred behaviour. Any change
to either would have to be pre-registered in a protocol committed before the
data it is measured against was seen — which is what `4b8e082` did for the
number now in place.

### The 31.7 % is a property of the normal distribution, not of this circuit

A one-SD margin puts ≈ 31.7 % of a **normal** distribution outside ±1 SD. That
is arithmetic about the normal distribution. It is not a measured crossing rate
of this decoder, whose aggregate `V_raw` is a difference of two spike-count
means over 45 neurons in a 20 ms window and is quantised at 1.724 Hz (avoid,
29 neurons) and 3.125 Hz (approach, 16 neurons) per spike. Nothing establishes
that it is normal.

It is also not the rate at which a **round** produces an action. A round
compares several candidates and selects one, and the selected candidate is the
argmax of `V`, so the round's action frequency is an order statistic of the
per-candidate distribution and is not the per-candidate frequency. The
execution policy then refuses some of what the decoder emitted — a `SELL` with
no inventory, a `BUY` with a position already open — so a third frequency,
after inventory and execution constraints, differs again.

Three different denominators, therefore three measured frequencies, reported
separately wherever this system reports behaviour:

1. **per candidate evaluation** — one batch of k = 8 presentations of one
   instrument;
2. **per decision round** — one market minute, after selection among the
   round's candidates;
3. **after inventory and execution constraints** — what actually became an
   order.

Measured, never presumed. `experiments/historical/results.md` reports all
three per partition and per instrument.
