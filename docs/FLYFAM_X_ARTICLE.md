<!-- Assumed publication state, 2026-09-17: trading is PAPER (real Pons market data, simulated positions, frozen brain `brains/trader-v1`); Bag Room eligibility now reads REAL on-chain $FLYFAM holders; no real money moves — LIVE execution, the Holder Payout Wallet and the creator-fee split are designed and documented, not active. Verify the real-holder switch against `/api/bags/bridge` before posting. -->

# FLY FAM — canonical launch article and thread

---

# OUTPUT A — LONG X ARTICLE

## We gave a fruit fly a memecoin terminal

Somebody was going to. It was us.

Not "AI inspired by a fly," and not a language model roleplaying as an insect. We took the measured wiring of a real fruit-fly nervous system, built it into a spiking simulation, pointed it at a live memecoin launchpad, and let it pick. Then we handed the exit to you.

### What the brain actually is

A connectome is a wiring diagram of a nervous system, measured rather than guessed: someone slices a real brain, images it with an electron microscope, traces every neuron and synapse, and publishes the map.

Ours is MaleCNS v1.0, a male *Drosophila melanogaster*, from FlyEM at HHMI Janelia, the University of Cambridge, the MRC Laboratory of Molecular Biology and Google Research, CC-BY 4.0. We pulled 1.03 GB of it, hashed it into our own manifest, and built our matrices from 151,856,684 rows of measured synaptic weight: **165,122 neurons and 10,228,000 signed connections.**

Now the part most projects skip. A connectome is anatomy: who is wired to whom. It does not give you neural dynamics, synapse strengths in millivolts, senses, or what counts as a reward. All of that is modelling and all of it is ours, including the global gain, which we measured ourselves because the inherited defaults saturate the whole network at about 440 Hz. So: a model constrained by a real animal's wiring, not a fly brought back from the dead. Smaller claim, and the only one the data supports.

### What came from the original work

The category is not ours. The Flybrain / flycoinrh project got there first — same dataset, same neuron count, a real simulation driving a real launchpad. MIT licensed, credited in our `NOTICE.md`, vendored unmodified at `5aab4e78` so anyone can diff it. They opened the door. We are not affiliated with them, the dataset's authors or PONS, and none of them endorse a trading project.

### What we audited

We did not fork a repo, swap the ticker and call it science. Before any market code we audited the upstream simulation, the vendored copy byte-frozen so our tests could not quietly "fix" it. The matrix convention checked out. The learning path did not.

The mushroom body is where a fly forms associations: dopamine neurons write into it, Kenyon cells carry the odour, output neurons read the result. Upstream classified each output neuron by reading `W[dan][:, mbon]`. Under the post-by-pre convention the rest of the codebase uses, that reads **output-to-dopamine feedback**, not dopamine input. Both circuits are real, and in the mushroom body they cross. We proved it on a nine-neuron synthetic graph: fed only real dopamine edges the classification returns nothing, fed only feedback edges it fills up completely.

Transposing the indices does not fix it: the graph builder signs dopaminergic edges 0.0 and drops zero-weight edges, so those connections are not in the fast graph at all and the correct read is identically zero. Learning switches off.

So the fix is structural and it is ours: build a **second, unsigned modulatory matrix** from the same data, keep anatomy, fast transmission and dopamine in three separate matrices, then correct the indexing. That recovered 241,702 dopaminergic edges the sign rule had deleted and moved 46 of 97 output neurons into a different compartment, sorting the way the hemibrain literature describes.

We did not "fix the fly brain," and the original project is not fake. One indexing defect, corrected in our own code — and run upstream's code over our graph and their README still reproduces exactly, split included.

Then we tested whether the corrected path learns. Pre-registered, committed before the runner existed. Pair an odour with punishment and its later response at the punished compartment falls from 34.9 Hz to 10.2 Hz, negative in 8 of 8 seeds. With plasticity off the same run moves exactly 0.000, and every synapse that moved was on the punished side.

Conditioning works. Remember that word.

### The experiments, including the failures

We tried to train her into a better trader. She mostly learned to stop trading.

First we caught our own mistake: the outcome we taught from and the horizon we graded on did not line up. All 42 trades exited before the evaluation horizon, and on 17 the two signs disagreed. Rebuilt aligned: **no improvement detected.** ΔAUC +0.0058, 95% interval [−0.0584, +0.0664]. Chance, and neither "not enough data" condition fired, so it is a read null rather than a shrug.

Then real Pons data. Twelve hours, 462,056 events, 9,474 launches, split 70/30 by time: train on the first part, freeze, grade on later candidates she had never learned from.

Fifteen teaching episodes, all fifteen punishments. The trained brain ranked **worse** than the untrained one, ΔAUC −0.1769 [−0.2180, −0.1246], and BUY crossings went from 35.29% to **exactly 0.00%** in every block. We had built a fly that refused to buy anything.

So we changed the teacher: grade each candidate against the others in its own tick, best of the cohort rewarded, worst punished, even when everyone lost money. 19,665 lessons, half of them rewards, zero clipping. Same wall: ranking −0.1329 [−0.1941, −0.0655], BUY rate 0.05% against 43.58%, 15% of plastic synapses driven to the floor and 22% of candidates producing no usable readout at all. This rule only depresses. Teach it long enough and it does not get smarter, it goes quiet.

Both evaluations failed our own pre-registered adequacy conditions, so both are published INCONCLUSIVE instead of quoting the number we could have quoted.

**The fly can be conditioned. Conditioning is not alpha.**

One consequence you can check: the brain in production, `brains/trader-v1`, is the clean reference, every plastic synapse still at 1.0, never depressed by a single lesson. We shipped the fly that was never taught, because teaching made her worse. Her digest is asserted on every start, and a mismatch refuses to trade.

### Why memecoins

Not because they are easier to predict, but because a fly needs an environment, and stock bars give you six hours a day and a handful of instruments. Pons gave us 9,474 launches in twelve hours and a fresh cohort every thirty seconds.

What runs today: Pons V2 ingestion from Robinhood Chain (4663) through our own node, exact bonding-curve reconstruction, an admission rule requiring two valid trades in the last two minutes, ten causal market features encoded onto the olfactory pathway across twenty glomerular channels, eight presentations per candidate, a decoder reading approach-versus-avoidance output neurons in Hz, and paper fills priced against the curve's own integer math.

What does not run: the eyes. Her encoder implements olfaction and nothing else — `visual`, `taste` and `mechanosensory` sit in the code as extension points routed nowhere. She does not see the market. She smells it.

### Why there is a cartoon fly

Because it is funny, and the funny part is the product. She sniffs while candidates are evaluated, snaps forward when she picks, droops in drawdown, and on a reward throws her head back through five body-laugh pulses with a laugh synthesized in your browser. When the crew votes HOLD she dances, at an authored 110 BPM that means nothing at all. There is a studio pose where she smokes, parked in the rig viewer.

The rule we do not break: **the neurons are real simulation data, the cigarette is not neuroscience.** Brain numbers on the site are measured telemetry in the decoder's units; the animation layer is theater and says so in the code. No pose feeds a decision, and no decision is inferred from a pose.

### The Bag Room

The fly controls entry, and only entry. When she picks and a position opens, a **Bag** is created: we snapshot $FLYFAM holders at the last finalized block before the entry block, hash the address set, and freeze it. That is the crew, permanently. You cannot see a green position and buy your way in, and you cannot sell and lose your place either. Later buyers are eligible for future bags.

Inside, a round every thirty seconds. Sign HOLD or EXIT with your wallet: EIP-712, no gas, no transaction, no approval. More HOLD keeps it open; more EXIT, or a tie with real votes cast, requests the sale; zero votes is recorded as no community action, never as consent.

**One eligible wallet, one vote.** More tokens does not buy more votes.

Economic share is separate on purpose: if a bag closes with real profit, your allocation is proportional to your snapshot balance, and you need not vote, chat, show up or still hold. Voting is a decision, so one wallet one vote. Money is money, so proportional.

Chat is open: anyone reads, any wallet that proves itself with a signature writes as VISITOR, only snapshot-eligible wallets vote and claim as CREW. Every vote and result lands in a hash-linked audit journal.

**The community does not choose what the fly buys. The fly finds the bag. The Fam decides when to leave.**

### The money, exactly as it stands

Designed, documented, not switched on: the bankroll funds the position; principal returns to it at close; positive **net realized** profit goes to that bag's snapshot holders; a loss creates no holder debt; claims are signed against the frozen snapshot and paid from a dedicated wallet that never holds inventory and never signs a trade, with the holder paying zero gas. We chose that over a bespoke vault contract on purpose: a trustless vault is a large new attack surface written mostly for the screenshot. So here is the label. **This is backend-managed custody, not trustless contract enforcement.**

Token fees are a separate flow. $FLYFAM launched on PONS with a 1% base fee and a 1% creator tax on a native ETH pair, verified on chain rather than assumed, and the intended internal split of the creator share is holders, fly and owner at 7:3:7. The worker that performs it **has not been written**: our first reading of the mechanics did not survive contact with the verified curve source, and we wrote that down instead of shipping it.

### Where this stands today

- **Trading is PAPER.** Real market, real launches, real curve math, simulated fills. No wallet signs anything, and no live-execution flag is set in this deployment.
- **The brain is frozen.** Digest asserted at every start, weights never move. A REWARD card is a recorded consequence plus theater, not learning.
- **Bag Room eligibility now reads real on-chain $FLYFAM holders.** Real snapshots, real signatures, real votes, governing paper positions.
- **No real money has moved to any holder.** Payouts and the fee split are built or designed and switched off. There are no live payout hashes and we will not invent any.
- **The site is live** at flyfam.xyz: guide, science panel, brand kit, audit endpoints, receipts.
- **No eyes.** The visual pathway is not implemented.
- **The tree is not public today.** The failures above live in it as pre-registered protocols and reports. The receipts, the audit journal and the live state are public.

### Where this goes

Real money is a switch we made hard to flip: a cost gate that refuses an entry whose own exit would cost more than 600 bps, wallets that do not exist yet, a fee worker nobody has written. After that, more bags, more crew, and a history where every bag is something that happened to the people who were in the room.

We tested a fly. She failed to become a trader. We kept the failure, published the numbers, and built the game around what she can do.

**THE FLY PICKS. THE FAM DECIDES.**

---

# OUTPUT B — LAUNCH THREAD

*16 tweets. Media positions marked on tweets 2, 5, 8, 10 and 12 as specified.*

**1/**
We gave 165,122 simulated fruit-fly neurons a memecoin terminal.

Not AI "inspired by" a fly. The measured wiring of a real *Drosophila* brain, running as a spiking simulation, picking tokens on Pons.

Then we made the holders responsible for what happens next.

🧵

---

**2/** `[TWEET 2 — connectome / brain image]`
A connectome is a wiring diagram of a nervous system, traced from electron-microscope images of a real brain.

Ours is MaleCNS v1.0 — FlyEM/HHMI Janelia, Cambridge, MRC LMB, Google Research. CC-BY 4.0.

165,122 neurons. 10,228,000 measured connections.

> *Media: the science panel of the public guide, https://flyfam.xyz/#how-it-works/brain — captured at `data/runtime/site-v1/output/guide/chromium-desktop-brain.png`.*

---

**3/**
Honest limit, up front: a connectome is anatomy. It does not give you neural dynamics, synapse strengths in mV, senses, or what counts as a reward.

All of that is modelling, and all of it is ours.

A model constrained by a real animal. Not a resurrected fly.

---

**4/**
Credit where it's owed: the original Flybrain / flycoinrh project opened this category. MIT, same dataset. It sits in our tree vendored unmodified at `5aab4e78` so anyone can diff it.

We didn't invent connectome trading. We built a different product on it.

---

**5/** `[TWEET 5 — experiment screenshot]`
Then we audited the code.

The learning path indexed dopamine backwards: it read output→dopamine feedback instead of dopamine input. Proved on a 9-neuron synthetic graph.

And transposing it alone breaks learning — the dopamine edges aren't in the fast graph at all.

> *Media: `docs/UPSTREAM_NOTES.md` §2 "The evidence" table, or the frozen audit suite result (43 passed, 2 strict xfail).*

---

**6/**
Our fix: build a second, unsigned modulatory matrix, keep anatomy / fast transmission / dopamine apart, then correct the read.

Recovered 241,702 dopamine edges the sign rule had deleted. 46 of 97 output neurons changed compartment.

One defect, fixed in our own code.

---

**7/**
Does it learn? Pre-registered test, committed before the code that runs it existed.

Pair an odour with punishment: its later response falls 34.9 Hz → 10.2 Hz. 8/8 seeds. Plasticity off = exactly 0.000.

Conditioning works.

Hold that thought.

---

**8/** `[TWEET 8 — fly sniffing token cards]`
Then we tried to train her into a trader.

She mostly learned to stop trading.

Real Pons data, 15 teaching episodes, all punishments. The trained brain ranked WORSE than the untrained one. BUY rate: 35.29% → 0.00%.

We built a fly that refused to buy anything.

> *Media: the live broadcast mid-round with the fly over the watchlist — `data/runtime/site-v1/output/guide/chromium-landing.png`, or the poster `spectacle/static/assets/flyfam/poster-v1.png`.*

---

**9/**
We changed the teacher — grade each candidate against its own cohort instead of an absolute target. 19,665 lessons, half rewards.

Same wall. BUY rate 0.05%. 15% of plastic synapses pinned to the floor.

The rule only depresses. Teach it long enough and it goes quiet, not smart.

---

**10/** `[TWEET 10 — Bag Room HOLD/EXIT]`
Both runs failed our own pre-registered conditions, so both are published INCONCLUSIVE. The fly in production is the one never taught.

So she does what a fly does. She picks — and a BAG opens, snapshotting $FLYFAM holders at the last finalized block before entry.

> *Media: the Bag Room voting panel — `output/bag-room/desktop-hold.png` and `data/runtime/site-v1/output/real-paper-bridge/real-position-exit-votes.png`.*

---

**11/**
That list is frozen. It's the crew.

You can't see a green position and buy your way in. You can't sell and lose your place either.

Rounds every 30 seconds, sign HOLD or EXIT — no gas, no transaction.

**1 eligible wallet = 1 vote.** More tokens does not buy more votes.

---

**12/** `[TWEET 12 — payout / bag receipt]`
Economic share is separate on purpose: allocation is proportional to your snapshot balance, and you don't have to vote, chat, show up or still hold.

Principal back to the fly. Positive net realized profit to that bag's holders. A loss creates no holder debt.

> *Media: a closed-bag receipt — `data/runtime/site-v1/output/real-paper-bridge/real-worker-receipt.png`. The claim screen `output/payout/claim-paid.png` is a local test fixture and must be captioned as one.*

---

**13/**
Chat is open. Anyone reads. Any wallet that proves itself with a signature writes, tagged VISITOR. Only snapshot-eligible wallets vote and claim, tagged CREW.

Every vote and round result lands in a hash-linked audit journal you can page through.

Come argue with the holders.

---

**14/**
Why memecoins? Not because they're predictable. Because a fly needs an environment. Pons gave us 9,474 launches in twelve hours.

And one thing we won't claim: she has no eyes. Her encoder implements olfaction and nothing else.

She doesn't see the market. She smells it.

---

**15/**
Status, exactly:

▸ Trading is PAPER. Real market, simulated fills.
▸ Brain frozen, digest checked at every start.
▸ Bag Room now reads real on-chain $FLYFAM holders.
▸ No real money has reached any holder. Payouts and the fee split are built and OFF.
▸ No live payout hashes.

---

**16/**
She sniffs, picks, droops, laughs, and dances when the crew votes HOLD. There's a studio pose where she smokes.

All of it is theater, and the code says so.

**The neurons are real simulation data. The cigarette is not neuroscience.**

flyfam.xyz

**THE FLY PICKS. THE FAM DECIDES.**
