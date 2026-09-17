# Flytrade — Canonical Specification

> This is the canonical product/engineering prompt for the project. It is the source of truth for scope,
> boundaries, and phase gates. Operational state lives in the session log; this file changes only by owner decision.

You are the principal engineer responsible for building a production-grade autonomous market experiment based on the open-source Flybrain project.

REFERENCE IMPLEMENTATION

Upstream repository:
https://github.com/fruitflydev/flycoinrh

Before writing code:

1. Clone and inspect the repository in full.
2. Read README.md and the core implementation, especially:
   - build_graph.py
   - flysim.py
   - flyeye.py
   - mushroom.py
   - roam.py
   - rhlive.py
   - rhprovider.py
   - site/
3. Understand the connectome representation, matrix orientation, sensory inputs, neural simulation, motor readouts, plasticity mechanism, persistence, browser visualization, and safety boundaries.
4. Inspect the upstream LICENSE and preserve all required notices and attribution.
5. Do not blindly trust claims in the README. Verify important behavior against the implementation.
6. Write an ARCHITECTURE.md documenting what is reused, what is replaced, and any upstream behavior that could not be independently verified.

PRODUCT

We are building a live experiment in which a simulated biological fruit-fly nervous system interacts with real financial market data.

The core question is:

Can a fruit fly brain learn anything from a financial market through repeated reward and punishment?

This is NOT an LLM trading agent.

No language model may make, alter, veto, rank, improve, or secretly substitute the fly's trading decisions.

The interesting outcome is not profitability.

The system remains valid and interesting if the fly loses money, behaves irrationally, develops strange preferences, repeatedly chooses the wrong asset, or eventually exhausts its experimental bankroll.

The system must therefore preserve failures rather than optimize them away.

CORE LOOP

The canonical loop is:

REAL MARKET
    ↓
MARKET OBSERVATION
    ↓
SENSORY ENCODER
    ↓
BIOLOGICAL CONNECTOME SIMULATION
    ↓
ACTION DECODER
    ↓
TRADE INTENT
    ↓
BOUNDED EXECUTION ENGINE
    ↓
REALIZED OUTCOME
    ↓
REWARD / PUNISHMENT
    ↓
BIOLOGICALLY CONSTRAINED PLASTICITY
    ↓
PERSISTENT BRAIN STATE
    ↓
NEXT OBSERVATION

The loop runs continuously.

MARKET UNIVERSE

Design the system for a configurable small universe of liquid instruments.

Do NOT hardcode specific symbols into the neural architecture.

The initial configuration should support approximately six simultaneous instruments.

Market providers must be adapters.

The simulation must not depend directly on a specific exchange, blockchain, broker, DEX, launchpad, or token.

MARKET DATA

Create a normalized MarketSnapshot representation.

At minimum it should be capable of representing:

- timestamp
- instrument
- current price
- short-horizon returns
- volume
- relative volume
- realized volatility
- recent high/low position
- recent price path

Do not use human technical-analysis labels such as:

bullish
bearish
oversold
breakout
good trade
bad trade

Do not feed RSI, MACD or handcrafted trading recommendations into the brain in V1.

The brain should receive measurements, not our interpretation of them.

SENSORY ENCODING

This is one of the most important parts of the project.

Build a deterministic, versioned sensory encoder that transforms normalized market state into stimulation of actual sensory populations available in the connectome.

Requirements:

- preserve biological topology wherever practical;
- document exactly which market measurement stimulates which neural population;
- keep encoding deterministic;
- make all normalization rules explicit;
- prevent future information leakage;
- prevent asset identity from accidentally leaking through implementation artifacts;
- support replaying the exact historical sensory state;
- version the encoder so experiments remain reproducible.

Do not arbitrarily map:

price up = reward
price down = punishment

Market movement is sensory information.

Reward and punishment occur only AFTER the fly has acted and the outcome becomes known.

ACTION SPACE

Keep V1 deliberately small.

The brain must ultimately produce:

BUY
SELL
WAIT

and an instrument selection.

Do not give the brain arbitrary position sizing in V1.

Position sizing belongs to deterministic execution policy.

The neural output must be derived from explicitly documented populations or circuits in the connectome.

Do not simply attach BUY/SELL labels to arbitrary neurons because they produce convenient results.

Investigate candidate output populations, document the biological justification, measure their behavior, and create deterministic decoding rules.

If no scientifically defensible mapping exists for a desired action, document the limitation instead of fabricating one.

DECISION INTEGRITY

Every decision must generate an immutable DecisionRecord containing enough information to reproduce it:

- decision id
- brain-state version/hash
- sensory-encoder version
- exact MarketSnapshot
- exact encoded stimulus
- relevant neural outputs
- selected instrument
- selected action
- execution-policy version
- timestamp
- random seed where applicable

A future auditor should be able to replay a decision and determine why the software produced it.

EXECUTION

Separate cognition from execution completely.

The brain emits TradeIntent.

A deterministic ExecutionEngine converts TradeIntent into an executable order.

The execution engine is NOT intelligence.

It exists only to enforce mechanical constraints such as:

- allowed instruments
- maximum position size
- maximum simultaneous exposure
- minimum time between trades
- available bankroll
- stale-price rejection
- duplicate-order protection
- slippage limits
- kill switch

All limits must be configurable.

Never invent production financial limits.

Ship safe simulation defaults and require explicit configuration for any real-money mode.

REAL MONEY MUST NOT BE REQUIRED TO DEVELOP OR TEST THE SYSTEM.

Implement:

PAPER mode
REPLAY mode
LIVE adapter interface

LIVE must remain disabled by default.

Do not integrate any specific live venue unless explicitly instructed later.

OUTCOME

A trade becomes eligible for learning only when its outcome is objectively known.

Design a canonical OutcomeRecord.

It must distinguish:

- unrealized PnL
- realized PnL
- fees
- slippage
- net realized PnL

Reward must never be generated from a temporary favorable price movement that later disappears.

The outcome rule must be deterministic and versioned.

LEARNING

Reuse the upstream biological learning mechanism only after verifying it.

Inspect mushroom.py carefully.

Verify:

- matrix orientation
- presynaptic/postsynaptic indexing
- PAM/PPL1 directionality
- KC→MBON synapse selection
- eligibility traces
- depression direction
- persistence
- recovery/forgetting

There is a potential directional inconsistency in the upstream implementation around dopamine-to-MBON classification relative to the matrix convention used by build_graph.py/flysim.py.

DO NOT assume the upstream implementation is correct.

Write focused tests proving the intended direction on a small synthetic graph before applying it to the full connectome.

If the suspected issue is real, document it and correct it in our implementation.

The learning event should conceptually be:

profitable realized outcome
    → reward event

negative realized outcome
    → punishment event

neutral / insignificant outcome
    → configurable neutral treatment

However, do not claim that financial profit is biological sugar or that loss is literally biological pain.

This is an experimental mapping from external outcome to biological reinforcement circuitry.

The mapping must be explicit in documentation and UI.

CRITICAL EXPERIMENTAL RULE

The system must never silently optimize itself for profitability.

No hidden:

- reinforcement-learning agent
- LLM
- strategy model
- optimizer
- heuristic fallback
- technical-analysis strategy
- human override

may replace the connectome's decision.

If the fly makes terrible decisions, record them.

If it loses repeatedly, record them.

If it develops pathological preferences, preserve them.

If it performs unusually well, preserve that too.

The experiment is the behavior.

MEMORY AND IDENTITY

The fly must persist across process restarts.

Persist:

- biologically permitted learned state
- experiment birth time
- total decisions
- completed trades
- wins
- losses
- realized PnL
- current bankroll
- per-instrument behavior
- streaks
- largest win
- largest loss
- reward count
- punishment count
- relevant neural/plasticity statistics

Never rewrite historical results.

Never reset learning automatically because performance becomes bad.

A reset creates a new ExperimentIdentity / Season.

SEASONS

Support explicit seasons.

A season has:

- immutable ID
- birth timestamp
- initial brain-state hash
- sensory-encoder version
- action-decoder version
- outcome-rule version
- starting bankroll
- ending bankroll
- complete event history

A new season must never overwrite the previous one.

OBSERVABILITY / LIVE EXPERIENCE

Build the backend and frontend as one coherent product.

The frontend should make the experiment understandable in seconds.

Primary live state should show:

- current market observations
- what the fly is currently sensing
- neural activity
- relevant output populations
- current decision process
- selected instrument
- BUY / SELL / WAIT
- open position
- countdown / evaluation state where applicable
- realized result
- reward or punishment event
- current bankroll
- lifetime PnL
- wins / losses
- current streak
- per-instrument history

When reward or punishment occurs, it should be visually obvious that the learning event entered the neural system.

The visualization must be derived from real runtime telemetry.

DO NOT fabricate neural activity for animation.

If the simulation is offline, the UI must say it is offline.

Do not display decorative fake spikes.

PERSONALITY MUST EMERGE FROM DATA

Do not hardcode a personality.

Instead derive entertaining descriptors from measured history.

Examples:

TSLA obsession
SPCX trauma
NVDA favorite
five-loss streak
revenge trade

These labels must be deterministic functions of historical behavior and clearly separated from scientific telemetry.

They are presentation, not inputs to the brain.

BENCHMARKS

Track comparison baselines that DO NOT affect decisions.

At minimum:

- random action baseline
- simple buy-and-hold baseline
- appropriate market benchmark where data exists

Benchmarks are observational only.

Never feed benchmark performance back into the fly.

We should eventually be able to answer:

Is the fly doing better than chance?

without changing its behavior to make the answer look better.

EVENT LOG

Everything important becomes an append-only event.

Examples:

MARKET_SNAPSHOT
SENSORY_STATE
BRAIN_STEP
DECISION
ORDER_REQUESTED
ORDER_FILLED
POSITION_OPENED
POSITION_CLOSED
OUTCOME
REWARD
PUNISHMENT
LEARNING_APPLIED
BANKROLL_CHANGED
SEASON_STARTED
SEASON_ENDED

Use idempotency keys where external actions could be duplicated.

A crash/restart must not duplicate an order or learning event.

REPLAY

Replay is mandatory.

Given:

- historical market data
- starting brain state
- encoder version
- decoder version
- execution policy
- seeds

we must be able to replay a season deterministically as far as deterministic components permit.

Differences caused by external execution must be represented explicitly rather than hidden.

TESTING

Create serious tests before considering the system complete.

At minimum:

1. connectome loading integrity
2. matrix orientation
3. sensory encoder determinism
4. no future-data leakage
5. action decoder determinism
6. synthetic reward-path test
7. synthetic punishment-path test
8. learning persistence across restart
9. season immutability
10. DecisionRecord reproducibility
11. duplicate execution prevention
12. duplicate reward prevention
13. stale market-data rejection
14. bankroll accounting invariants
15. realized PnL accounting
16. replay determinism
17. PAPER mode cannot submit live orders
18. LIVE mode impossible without explicit arming
19. frontend telemetry corresponds to actual backend state
20. benchmark system cannot influence decisions

ARCHITECTURE

Prefer explicit modules over a giant service.

A reasonable target structure is:

apps/
  api/
  web/
  worker/

packages/
  connectome/
  market/
  sensory/
  brain/
  decoder/
  execution/
  learning/
  accounting/
  experiment/
  replay/
  telemetry/
  shared/

Do not force this structure if the existing repository suggests a cleaner migration path.

Keep scientific computation isolated from web presentation.

Keep external providers behind interfaces.

Keep execution isolated from cognition.

DATABASE

Use a persistent relational database for canonical experiment state.

Use append-only event history for auditability.

Do not make browser local storage authoritative.

Schema migrations must be explicit.

Store enough information to reproduce historical decisions even after encoder or decoder versions change.

SECURITY

No private keys in source code.

No private keys in frontend code.

No secret values in logs.

No live execution from the browser.

No unrestricted RPC passthrough.

No arbitrary remote command execution.

External market/execution providers must be allowlisted/configured server-side.

LIVE mode requires an explicit server-side arm flag.

A process restart must return to a safe state unless explicitly configured otherwise.

DOCUMENTATION

Create:

README.md
ARCHITECTURE.md
SCIENCE.md
EXPERIMENT.md
SAFETY.md
REPLAY.md
UPSTREAM_NOTES.md
the session log

SCIENCE.md must clearly distinguish:

- measured biological anatomy
- simulation assumptions
- our sensory mapping
- our action mapping
- our reward/punishment mapping
- actual biological plasticity mechanism
- modeling choices
- unknowns

UPSTREAM_NOTES.md must record:

- upstream commit used
- upstream license
- reused files/modules
- modified behavior
- discovered upstream issues
- verification status

the session log is canonical operational state for future coding sessions.

PRODUCT BOUNDARIES

DO NOT build:

- a token
- tokenomics
- launchpad integration
- holder rewards
- fee distribution
- staking
- NFTs
- governance
- marketing site copy
- social-media automation
- referral systems
- a specific blockchain integration

Those are deliberately outside this system.

The product must work completely without any of them.

DO NOT prematurely optimize the system around any future distribution or launch mechanism.

IMPLEMENTATION STRATEGY

Do not attempt the entire product in one uncontrolled rewrite.

Work in verified phases.

PHASE ZERO — UPSTREAM AUDIT

Clone and pin upstream.

Understand and test:

- graph construction
- simulation
- sensory path
- motor/output path
- plasticity
- persistence

Produce UPSTREAM_NOTES.md.

No product implementation until the core assumptions are understood.

PHASE ONE — OFFLINE EXPERIMENT CORE

Build:

MarketSnapshot
SensoryEncoder
BrainRunner
ActionDecoder
DecisionRecord
OutcomeRecord
Reward/Punishment
persistent learning
event log

Use synthetic and recorded market data only.

Gate:

A complete deterministic decision → outcome → learning → next-decision cycle works offline and is replayable.

PHASE TWO — PAPER MARKET

Add a real market-data adapter and paper execution.

No real money.

Gate:

The system runs continuously, survives restart, never duplicates decisions/outcomes, and produces a complete auditable season.

PHASE THREE — LIVE EXPERIENCE

Build the public live UI and telemetry.

Gate:

A stranger can open the page and understand within seconds:

what the fly sees,
what its brain is doing,
what it chose,
whether it won or lost,
and how its historical behavior is evolving.

PHASE FOUR — LIVE EXECUTION INTERFACE

Only build the generic interface and safety envelope.

Do not connect a production venue unless separately authorized.

Gate:

LIVE mode is impossible to activate accidentally.

DEFINITION OF DONE FOR THIS WAVE

Do not claim the complete project is finished merely because code compiles.

For the first implementation wave, stop after PHASE ONE is genuinely complete.

Required evidence:

- pinned upstream commit
- upstream audit
- synthetic orientation tests
- complete offline loop
- persistent learning
- deterministic replay
- append-only event history
- tests green
- type/lint checks green where applicable
- documentation updated
- the session log containing exact current state and next phase

ENGINEERING BEHAVIOR

Do not hide failures.

Do not weaken tests to obtain green.

Do not replace biological behavior because the output looks stupid.

Do not invent scientific claims.

Do not invent financial performance.

Do not introduce unnecessary dependencies.

Do not rewrite verified upstream functionality without a reason.

When uncertain about a scientific or architectural assumption, investigate it and document the uncertainty.

Make small, reviewable commits.

At each phase boundary, stop and report:

- what changed
- files changed
- tests run
- exact results
- unresolved risks
- assumptions
- commit hash
- recommendation: GO / NO-GO for the next phase

START NOW WITH PHASE ZERO.

Do not begin PHASE ONE until the upstream audit is complete enough to establish the connectome orientation, sensory path, action-output candidates, and learning semantics.

---

## Phase 0.5 — canonical amendment (owner, 2026-09-11, original in Portuguese)

D1 AUTORIZADO — DOWNLOAD DOS DADOS E CORREÇÃO DO NÚCLEO

Execute uma onda delimitada de implementação: Fase 0.5.

Objetivo:
Carregar o conectoma real, corrigir nossa implementação de
neuromodulação e demonstrar uma associação estímulo → reforço
→ mudança posterior de resposta.

Não reabrir a concepção do produto.
Não implementar token, lançamento, distribuição, venue ou execução live.

1. DADOS E PROVENIÊNCIA

Baixar os três arquivos necessários do MaleCNS v1.0, usando os
links publicados em:
https://male-cns.janelia.org/download/

- body-annotations-male-cns-v1.0-minconf-0.5.feather
- body-neurotransmitters-male-cns-v1.0.feather
- connectome-weights-male-cns-v1.0-minconf-0.5.feather

Não baixar imagens de microscopia, meshes, banco Neo4j ou tabelas
adicionais nesta onda.

Registrar URLs, versão, tamanhos, hashes locais e atribuição.
Validar integridade e esquema antes da construção do grafo.
Não commitar os arquivos grandes.

Manter upstream/ intacto no commit já fixado.
Registrar também o SHA completo.

2. CONSTRUÇÃO CORRETA DO GRAFO

Preservar a conectividade anatômica antes de aplicar os sinais
de neurotransmissão.

Separar:
- conectividade anatômica não negativa;
- matriz de transmissão rápida;
- conectividade dopaminérgica usada pela regra modulatória.

Todas devem usar o mesmo índice de neurônios e a convenção
explícita [pós, pré].

Não transformar dopamina em excitação rápida apenas para fazer
o aprendizado aparecer.

Documentar filtros, limiares e arestas removidas.
Não reutilizar automaticamente um filtro da transmissão rápida
para a camada modulatória sem avaliar seu efeito.

3. CORREÇÃO DA PLASTICIDADE

Implementar a correção em código nosso, sem alterar upstream/.

Provar em testes pequenos:
- orientação DAN→alvo;
- preservação das conexões modulatórias;
- seleção correta das sinapses KC→MBON;
- atualização somente das sinapses elegíveis;
- aplicação efetiva dos pesos atualizados na simulação seguinte.

Rederivar as populações usando os dados reais.

Não tratar maior contagem de entradas PAM/PPL1 como prova
suficiente de valência comportamental.

Separar claramente:
a) conectividade observada;
b) interpretação funcional sustentada por literatura;
c) regra de modelagem escolhida por nós.

Quando a identificação for ambígua, registrar a ambiguidade.
Não inventar equivalências entre nomes ou compartimentos.

4. CAMINHO SENSORIAL FUNCIONAL

Escolher estímulos de teste e populações sensoriais documentadas,
antes de avaliar resultados de treinamento.

Medir se o estímulo alcança:
entrada sensorial → KCs → MBONs/readout candidato.

Não injetar diretamente na saída escolhida para simular que
o restante do cérebro tomou uma decisão.

Se houver silêncio, diagnosticar o caminho.
Não inserir uma estratégia ou resposta artificial como fallback.

5. DEMONSTRAÇÃO MÍNIMA DE CONDICIONAMENTO

Construir um experimento pequeno, offline e reproduzível:
- apresentar padrões sensoriais A e B;
- medir respostas antes do condicionamento;
- associar os padrões a sinais de reforço definidos;
- reapresentar os mesmos padrões;
- medir respostas depois.

Comparar com controle de plasticidade desligada.
Incluir controle com reforço não associado ao estímulo para
distinguir associação de alteração global dos pesos.

Fixar previamente readout, protocolo e métricas.
Usar sementes registradas e mais de uma realização.

Mostrar separadamente:
- quais pesos mudaram;
- quais respostas neurais mudaram;
- qual efeito dependeu da associação estímulo/reforço.

Apenas mudar pesos ou incrementar um contador REWARD não fecha
esse requisito.

Não exigir rentabilidade ou prever mercado nesta demonstração.
Não ajustar o decoder depois de olhar os resultados para fabricar
um sucesso.

6. TEMPO, MEMÓRIA E PERSISTÊNCIA

Distinguir:
- estado elétrico;
- traços de elegibilidade;
- pesos aprendidos;
- histórico do experimento.

Definir explicitamente o que persiste entre chamadas, episódios
e reinícios.

Definir unidades de tempo e decaimento.
Não deixar a duração da memória depender acidentalmente da
frequência de chamadas do frontend.

O reforço deve corresponder à experiência que o originou.
Não aplicar um resultado atrasado à atividade de outro episódio.

Nesta onda, episódios sequenciais são suficientes.
Não construir concorrência de trades.

Checkpoint atômico, com validação de versão e grafo.
Falhas de gravação ou carregamento não podem ser engolidas.

7. EMENDA CANÔNICA DO ESPAÇO DE AÇÃO

Não precisamos encontrar BUY, SELL ou WAIT como funções
financeiras naturais dos neurônios.

É permitido um decoder experimental, explícito, determinístico
e versionado que traduza respostas neurais em ações.

Não é permitido que esse decoder use uma estratégia de mercado
para substituir a decisão neural.

Ausência de atividade deve ser registrada como NO_RESPONSE.
Ela pode resultar em nenhuma ordem, mas não deve ser apresentada
como uma escolha neural demonstrada de esperar.

Os candidatos DNa02 e MBONs continuam candidatos até medição.
Não declarar seleção de instrumento ou de ação já validada.

8. TESTES E FECHAMENTO

Preservar a evidência dos defeitos do upstream intacto.

Os testes da implementação corrigida devem passar normalmente.
Não fazer os xfails originais "virarem passes" alterando o upstream,
apagando a reprodução do defeito ou enfraquecendo assertions.

Entregar:
- manifesto dos dados;
- contagens reais de populações e arestas;
- correção revisável;
- evidência do caminho sensorial;
- resultados do condicionamento e controles;
- teste de persistência;
- comandos executados e resultados exatos;
- commit final e estado da árvore;
- documentação e HANDOFF atualizados.

Atualizar a recomendação GO/NO-GO para a Fase Um.

O gate é demonstrar que o circuito corrigido recebe estímulos
e que a plasticidade pode modificar sua resposta de maneira
causal e reproduzível.

Não confundir isso com prova de capacidade de prever mercado.

Execute a Fase 0.5 agora e pare no relatório de fechamento.

---

## Phase One — canonical amendment (owner, 2026-09-11, original in English)

PHASE ONE — CANONICAL DECISIONS AND IMPLEMENTATION SCOPE

Read the session log, docs/SPEC.md, the Phase 0.5 protocol,
results and implementation before changing anything.

The pasted session report contains truncated sentences.
Use repository artifacts as the source of truth.
Do not reconstruct missing measurements from the pasted text.

Preserve the completed Phase 0.5 baseline and upstream audit.

DECISION D2

Accept uniform gain 0.10 as the versioned experimental
operating point for Phase One.

This is a modeling parameter, not a measured biological constant.

Do not open a separate, unrestricted gain-calibration phase.
Do not optimize gain using trading returns or future labels.

As a bounded integration check, characterize the encoder's
actual input range at gain 0.10:
- silence;
- saturation;
- KC recruitment;
- MBON response variation;
- discrimination between different input patterns.

Include a small, predeclared local sensitivity check.
Report instability rather than hiding it.

If nominal encoder inputs collapse into silence or saturation,
fix or restrict the declared input operating range before
claiming a functioning decision loop.

No automatic gain tuning during operation.

DECISION D3

Use sequential presentation of instruments.

Use the olfactory sensory entry path exercised in Phase 0.5
as the initial substrate for the market encoder.

Do not implement visual navigation or DNa02-based instrument
selection in this wave.

One persistent learned brain evaluates the candidates.
Do not maintain an independently trained brain per instrument.

OBJECTIVE

Deliver an offline, replayable vertical slice:

historical market context
→ sensory sequence
→ connectome activity
→ fixed neural readout
→ instrument/action decision
→ simulated execution
→ realized outcome
→ episode-specific reinforcement
→ persistent learning
→ next decision.

No live venue, keys, blockchain, token, fees, distributions,
public frontend or deployment in this wave.

1. MARKET CONTEXT AND SENSORY ENCODER

Implement timestamped market observations and a versioned,
deterministic MarketToSensoryEncoder.

Encode a recent time sequence, not merely the latest price.

Start with a small measurement set:
- recent returns / price path;
- volume or relative volume when available;
- realized volatility.

Use causal normalization: information available by the
observation cutoff only.

Keep observation data and future outcome data in separate
interfaces. The brain and encoder cannot access future labels.

Map measurements into bounded stimulation of documented
sensory populations.

Document:
- populations and body IDs;
- feature-to-channel mapping;
- normalization;
- rate bounds;
- simulated presentation timing;
- random seeds.

Do not stimulate KCs, MBONs or reinforcement pathways directly
as a shortcut around the sensory path.

No "rising price = reward" or "falling price = punishment".
Market context and outcome reinforcement are separate inputs.

For this version, ticker identity is metadata, not a learned
financial preference encoded by hand.

Missing or stale data must have explicit handling.

2. FAIR SEQUENTIAL EVALUATION

Freeze one observation cutoff and one learned-state version
for each decision round.

Evaluate every candidate with that same learned-state version.
Do not apply reinforcement between candidates.

For this offline version, begin candidate evaluations from
equivalent transient-state snapshots and an explicitly defined,
reproducible randomization policy.

Keep learned weights shared. Temporary evaluation snapshots
are not separate persistent flies.

Ensure results do not depend accidentally on iteration order,
symbol spelling or array position.

Define deterministic tie handling without using market
features to break ties.

Test candidate-order permutation and symbol renaming.

Preserve each candidate's:
- encoded stimulus;
- neural readout;
- evaluation identity;
- eligible learning trace or equivalent evidence.

3. NEURAL READOUT AND ACTION DECODER

Implement a fixed, documented decoder using measured outputs
from the corrected circuit.

The decoder may aggregate and compare neural responses.
It must not contain a trading strategy, classifier, LLM or
learned policy operating outside the declared neural model.

Do not equate:
- PAM-associated MBONs with "BUY neurons";
- PPL1-associated MBONs with "SELL neurons";
- reduced firing with aversion in every population.

Separate:
a) modulation compartment;
b) supported functional interpretation;
c) our explicit action-mapping convention.

Register readout signs, aggregation, thresholds and tie rules
before examining trading outcomes.

Preserve BUY / SELL / WAIT as the product-facing action space.

For the offline execution fixture, use inventory-aware,
long-only semantics:
- BUY opens or increases permitted long exposure;
- SELL reduces existing exposure;
- WAIT leaves exposure unchanged.

Do not reinterpret SELL as opening an unimplemented short.

Distinguish:
- valid neural output decoded as WAIT;
- NO_RESPONSE;
- invalid/saturated neural state;
- execution-policy rejection.

The last three must not be presented as demonstrated neural
choices to wait.

4. PROVE THAT LEARNING REACHES THE DECODER

The Phase 0.5 report demonstrates an aversive conditioning
effect. Do not assume this validates both reinforcement
branches or the new action decoder.

Using the fixed decoder, add targeted demonstrations that:
- appetitive reinforcement can affect its output;
- aversive reinforcement can affect its output;
- effects depend on the eligible sensory experience;
- disabled plasticity removes the learned change.

Do not require every trial to flip a discrete action.
Report both continuous readout changes and resulting actions.

Retain the original controls and their stated limitations.
Do not present the zero-by-construction UNPAIRED control as
independent evidence of associative selectivity.

A counter increment or a changed weight alone is insufficient.
Show the causal path through to the decoder.

5. EPISODE-SPECIFIC CREDIT ASSIGNMENT

The selected decision must retain the correct sensory and
eligibility context.

A later outcome must not reinforce:
- the last candidate scanned;
- an unrelated instrument;
- another episode;
- an already settled decision.

For this wave, keep one unresolved decision/trade at a time.

Specify the relationship between:
- market time;
- simulation time;
- eligibility decay;
- outcome arrival.

If eligibility is retained or replayed across a delayed
financial outcome, document that as a modeling convention.
Do not silently stretch a biological time constant.

Add a concrete test:
evaluate A, then B, select A, settle A.
Only A's eligible experience may receive that learning update.

Prove that valid current traces are accepted, not only that
old traces are rejected.

Separate rejection counters by reason.
Do not use a large rejection count as evidence of correctness.

6. SIMULATED EXECUTION AND OUTCOMES

Use existing recorded data when available.

Otherwise support a documented local historical-data format
and deterministic synthetic fixtures. Do not purchase data or
introduce a provider account as a dependency for this wave.

Use one simple, versioned paper execution policy:
- fixed configurable sizing;
- one open position;
- explicit execution timing;
- explicit fee/slippage assumptions;
- cash, inventory and realized PnL accounting.

Execution occurs no earlier than information availability
plus the declared simulated execution delay.

Use a fixed configurable evaluation horizon for completed
episodes. Label mechanical expiry closures as POLICY_CLOSE,
not as a neural SELL decision.

Reward/punishment depends on net realized outcome.
No reinforcement from unrealized price movement.

No counterfactual rewards for unchosen instruments in V1.

Position sizing, thresholds and outcome rules must not be
selected after inspecting the evaluation-period PnL.

7. PERSISTENCE, EVENTS AND REPLAY

Reuse and extend the existing persistence implementation.

Every decision must link:
observation → encoded stimulus → brain version → readout
→ action → execution → outcome → learning event.

Record all versions, seeds and timestamps needed for replay.

Preserve append-only history and atomic checkpoints.

Test crash/restart behavior at the outcome/learning boundary:
an outcome must neither disappear nor update the brain twice.

Do not reset learned state after poor performance.

8. DELIVERY AND GATE

Deliver a runnable offline demonstration over multiple
instruments and completed decision/outcome cycles.

Required evidence:
- market-to-sensory mapping;
- actual encoder operating-range measurements;
- fixed decoder specification;
- reward and punishment integration tests;
- candidate-order and ticker-renaming tests;
- correct selected-episode reinforcement;
- accounting tests;
- restart and replay results;
- unchanged upstream audit;
- exact test commands and outcomes;
- commits, tree status and updated the session log.

Show a compact chronological trace:

what context was presented;
what the sensory encoder produced;
what the brain returned;
what action the fixed decoder produced;
what the simulated outcome was;
which eligible weights changed;
what happened on the next presentation.

No profitability threshold is required.

The gate is a working, auditable market-context → decision
→ outcome → learning loop, not evidence of trading alpha.

Implement Phase One and stop at its closing report.
Do not expand scope into public UI or live execution.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* Changing a neural response is not demonstrating a choice. Phase One must
  link the response to a decoder and show that experience changes the
  decision the system produces.
* "Less activity" is not automatically "dislike". What matters is which MBON
  population changed and how it takes part in the output readout — the balance
  between outputs — not whether a mean fell.
* Credit assignment: if six instruments are evaluated and the first is chosen,
  the later outcome must reach the chosen one's eligible trace, not the
  sixth's. The Phase 0.5 rejection counter alone does not settle this; the
  wave must prove the correct trace is accepted as well as old ones rejected.
* D2 is accepted because gain 0.10 was fixed before the conditioning results
  existed, not found by searching for a configuration that produced them.

### Fable addenda (reviewer, 2026-09-11) — binding for the Phase One wave

1. **Sensory channels.** The encoder draws only from the 50 candidate glomeruli
   of `experiments/conditioning/PROTOCOL.md` §2 (ORN → uPN path, listed in
   `docs/POPULATIONS.md` "Sensory populations chosen for Phase 0.5"). No new
   populations. Drive stays within [0, 150] Hz per ORN, presentation window
   20 ms, gain 0.10, exactly the protocol's regime. Every nominal encoder
   pattern must meet the protocol's three sanity criteria (non-silent MBON
   readout; KC active fraction below 0.25 in mean; pairwise KC Jaccard between
   distinct patterns below the protocol threshold). Failing that, restrict the
   declared input range — never raise the gain.
2. **D2 check, predeclared and capped.** Gains {0.08, 0.10, 0.12} × 8 seeds ×
   at least four nominal patterns spanning the feature range (strong up, strong
   down, flat/low-vol, flat/high-vol). One table: silence, saturation, KC
   fraction, MBON response SD across seeds, pairwise discrimination. Report
   only. No selection, no further sweep.
3. **Decoder pre-registration.** `docs/DECODER.md` and the decoder version in
   `flytrade/decoder.py` are committed **alone**, before any execution or PnL
   code runs (same discipline as `PROTOCOL.md`, commit `b9655ea`). The readout
   aggregates MBON rates per compartment using the corrected map in
   `flytrade/mushroom.py`. It carries a three-column table per compartment:
   modulation compartment | literature-attributed valence (labelled as
   attributed, not measured here) | our action-mapping convention. MBONs with
   no defensible attribution are **excluded** from the readout, not guessed.
   The sign convention may be fixed using the §4 conditioning demonstrations
   and is frozen at the commit that precedes §6. It is never touched after any
   PnL has been seen.
4. **WAIT is a margin rule.** A valence whose magnitude is below a predeclared
   θ decodes as WAIT. θ is stated in `DECODER.md` in units of the measured
   seed-to-seed SD of the baseline readout (e.g. 1 SD), not in PnL terms.
   `Action` gains no members; the record carries a separate `readout_status`
   ∈ {VALID, NO_RESPONSE, INVALID_STATE, POLICY_REJECT} so the four cases the
   owner lists stay distinguishable in every DecisionRecord.
5. **Sequential evaluation convention.** Per round: take one transient
   snapshot S0 (electrical + eligibility) after the previous episode settles.
   For each candidate: restore S0, present, read out, capture (readout,
   eligibility trace). Per-candidate RNG seed = hash(round_seed,
   candidate_stable_id); the stable id is an integer assigned at universe
   registration, independent of symbol string and of position. After
   selection, the selected candidate's post-presentation state becomes the
   ongoing state; the others are discarded. Ties resolve by lowest stable id.
6. **Eligibility across market time: stored-trace replay.** The selected
   episode stores its eligibility trace at decision time. When the outcome
   arrives — market-time later — reinforcement is applied to that stored
   trace, which is then discarded and the episode closed. The 836 ms / 625 s
   time constants in `flytrade/state.py` are not changed and act only within
   the simulation cycle. The learning event records
   `eligibility_source = "replayed_from_decision"` and the episode id.
7. **Data, offline only.** No network in this wave. A documented local CSV
   format (timestamp, open, high, low, close, volume, one file per symbol
   under `data/market/`, gitignored) plus seeded synthetic fixtures (random
   walk with regime shifts). The demonstration runs on the synthetic fixtures;
   the same runner accepts a dropped-in CSV. No provider code.
8. **Execution fixture v1, predeclared before any run.** Bar data. Decision at
   the close of bar t, execution at the open of bar t+1 (declared delay =
   1 bar). Fee and slippage in basis points, configurable, defaults stated.
   Horizon H bars, then `POLICY_CLOSE`. One open position, long-only, fixed
   notional. Outcome = net realized PnL. Reinforcement: sign from net PnL,
   magnitude = DAN drive rate proportional to |net PnL| / notional, clipped at
   a declared cap; positive routes to PAM, negative to PPL1, through the
   modulatory matrix — never by writing weights directly.
9. **Layout.** `flytrade/market.py` (observations, CSV, synthetic),
   `flytrade/encoder.py`, `flytrade/runner.py` (BrainRunner, sequential
   evaluation), `flytrade/decoder.py` (extended), `flytrade/execution.py`,
   `flytrade/records.py` (DecisionRecord, OutcomeRecord, event log, reusing
   `state.py` checkpoints), `experiments/phase_one/` (demo runner, trace,
   results). Tests in `tests/phase_one/`. `upstream/` and
   `tests/upstream_audit/` byte-identical at the end.
10. **Process and cost.** One Opus agent, sequential, one commit per section
    in the order 1 → 2 → 3(pre-registration) → 4 → 5 → 6 → 7 → 8. Full
    `pytest tests/` twice only at close. HANDOFF block ≤ 25 lines. No
    reopening of the graph build or the plasticity fix. Permutation, renaming,
    credit-assignment and crash tests are one test each; the crash test uses
    an injected fault at the outcome/learning boundary. No statistical hunting
    beyond addendum 2.

## D4 — k = 8 readout integration — canonical amendment (owner, 2026-09-11, original in English)

D4 APPROVED — FIXED K=8 READOUT INTEGRATION

Read the session log, DECODER.md, the Phase One implementation
and the conditioning v1/v2 reports before changing code.

Implement one bounded integration wave.

Preserve:
- uniform gain 0.10;
- the current 20 ms presentation window;
- the declared encoder input range and sensory populations;
- the current MBON membership and decoder sign convention;
- long-only offline execution semantics;
- the untouched upstream and its audit tests.

Do not add neurons, extend the presentation window, retune
gain, change the stimulus mapping, or optimize trading returns.

No live venue, public frontend, token, blockchain or economic
integration in this wave.

OBJECTIVE

Replace the single-presentation readout with a fixed
eight-presentation readout throughout the existing offline loop.

The invariant is:

8 neural measurements per candidate
→ 1 aggregate candidate readout
→ 1 final decision
→ at most 1 execution episode
→ 1 outcome-linked learning event.

1. REPEATED MEASUREMENT SEMANTICS

Freeze the market observation, encoder output, learned weights
and reference transient-state snapshot for the decision round.

Evaluate each candidate exactly eight times.

Each presentation starts from an equivalent copy of the
declared transient state. Do not carry electrical state or
eligibility from one measurement into the next.

Use distinct, reproducible random streams across replicates.
Record the seed policy and each replicate's seed.

Preserve candidate-order and ticker-renaming invariance.
Do not make symbol spelling, iteration order or process-level
hash randomization a source of preference.

All candidates use the same learned-state version.

No reinforcement, persistent weight mutation or repeated
forgetting during the measurement batch.

Distinguish measurement compute time from the canonical
experiment and market clocks.

Do not retry until a response appears.
Do not increase k for difficult observations.
Do not stop early after a desirable response.

2. AGGREGATION BEFORE DECODING

Aggregate neural counts/rates across all eight measurements,
then apply the fixed decoder once.

Do not majority-vote eight BUY/SELL/WAIT labels.
Do not choose the strongest or most favorable replicate.

Store per-replicate measurements as well as the aggregate:
- population firing rates;
- spike counts;
- readout status;
- continuous score;
- seed;
- eligibility reference.

A technically successful silent presentation contributes its
zero counts. Do not discard it to inflate the average.

Define aggregate status rules before evaluation.

Keep distinct:
- genuine absence of output activity;
- valid activity with a near-neutral aggregate score;
- saturation or invalid neural state;
- technical execution failure.

Do not hide saturation by averaging it with quieter trials.
Do not silently average only the technically successful subset.

Version the readout policy. Preserve k=1 as an explicit
regression/comparison mode, not an automatic fallback.

3. BASELINE AND WAIT MARGIN

Inspect the current baseline and WAIT normalization.

If the decoder expresses its margin in baseline SD units,
create a baseline compatible with the k=8 estimator.

Preserve the decoder formula and dimensionless margin
coefficient. Do not tune either to produce more trades.

Use a declared reference brain state, baseline stimulus set
and seed schedule. No future labels, PnL or desired action rate
may participate in calibration.

Record the resulting baseline artifact and its provenance.

Do not silently substitute standard error for standard
deviation. Define exactly which distribution is normalized.

Handle zero or degenerate baseline dispersion explicitly.
Do not hide it with an arbitrary divisor.

Freeze the baseline for the experiment version.
Do not continuously recenter learned preferences away.

Record the normalization change as a versioned amendment,
rather than describing the complete decoder pipeline as
numerically unchanged.

4. ONE NORMALIZED LEARNING EVENT

Preserve the eight eligibility traces belonging to the
selected candidate.

Use normalized contribution across those traces.

Canonical rule:
- compute each replicate's proposed weight delta using the
  same pre-update learning state and the same outcome;
- retain all existing eligibility, compartment and floor rules;
- average the eight proposed deltas;
- apply one atomic learning update.

Do not apply eight sequential full-strength rewards.
Do not select the trace that yields the largest update.

This aggregation is our modeling convention, not a claim
about eight separate biological experiences.

Required invariants:
- eight identical traces produce the same weight update as one;
- replicate permutation does not change the update;
- unselected candidates contribute no update;
- rejected or ineligible traces cannot modify weights;
- one outcome increments the learning-event counter once;
- a duplicate outcome cannot update weights again.

Extend the existing A/B credit-assignment test:
evaluate A eight times, then B eight times, choose A and
settle A. Only eligible contributions from A may be applied.

5. INDEPENDENT INTEGRATION CHECK

Preserve conditioning v1 as a failed protocol and v2 as the
explicitly revised protocol. Do not rewrite their history.

Before running the new evaluation, commit:
- the evaluation stimulus set;
- new seed schedules;
- metrics;
- aggregate status rules;
- pass/fail criteria.

Include additional encoder patterns not selected because they
passed conditioning v2.

Keep the evaluation bounded. Reuse existing fixtures and
the completed offline demo where appropriate.

Compare k=1 and k=8 on the same contexts and starting learned
states. Use a declared paired comparison design.

Measure:
- within-context readout variability;
- decision agreement across repeated measurement batches;
- NO_RESPONSE counts and denominators;
- WAIT separately from NO_RESPONSE;
- invalid/saturated observations;
- reward and punishment effects on the aggregate decoder.

Report all predefined contexts, including failures.

Eight measurements of one context are not eight independent
market predictions or eight independent learning episodes.

Do not promise zero NO_RESPONSE.
Do not relabel silence or lower thresholds to meet a target.

If the claimed readout improvement does not appear outside
the original v2 pair, report that result. Do not silently
change stimuli, gain, thresholds or k.

6. DATA PROVENANCE AND SCIENTIFIC LABELS

Resolve the report's phrase "real observations" from the
actual data artifacts.

Label every dataset explicitly:
SYNTHETIC or HISTORICAL_MARKET.

For historical data, record source, instruments, timestamps
and file hashes. For synthetic data, record its generator
and seeds.

Report NO_RESPONSE as numerator/denominator and state whether
the unit is a presentation, candidate evaluation or decision.

Retain PPL1-minus-PAM as the declared experimental decoder
convention. Do not describe grouping by dopamine innervation
alone as proof of universal behavioral valence.

No new literature-audit phase is required here.
Correct unsupported wording without changing the decoder.

7. RESTART, ACCOUNTING AND PERFORMANCE

Extend restart/replay coverage to:
- interruption during the eight-measurement batch;
- completion of a decision;
- outcome persistence;
- application of the normalized learning update.

An incomplete batch may be resumed or deterministically
recomputed, but must not mutate learned state twice or become
a different decision after restart.

Preserve accounting and exactly-once outcome processing.

Benchmark actual runtime for six candidates at k=1 and k=8:
- median and p95 round latency;
- neural evaluation time;
- checkpoint/logging overhead;
- peak memory;
- hardware and process configuration.

Measure end-to-end cost. Do not assume that an eightfold
increase in presentations equals exactly eightfold total
latency.

Do not introduce distributed infrastructure or change the
scientific model to meet a guessed performance target.

8. DELIVERY

Deliver:
- a runnable k=8 offline demonstration;
- the versioned readout and baseline artifacts;
- normalized learning implementation and tests;
- independent evaluation results;
- data provenance clarification;
- restart/replay evidence;
- measured performance;
- exact test commands and outcomes;
- commits, clean-tree status and updated the session log.

Keep the two strict upstream xfails as upstream defect
evidence. Do not remove or weaken them.

Run the complete gate twice at closure, following the existing
workflow.

Conclude separately:
A. Is k=8 integrated correctly?
B. Does it improve readout stability on the declared evaluation?
C. What remains necessary for historical/live market data
   and a viewer-facing experience?

Do not require profitability.

Stop at the closing report. Do not expand into the next phase.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* D4 resolved as option (a): k = 8 fixed, gain 0.10, 20 ms window, the same
  MBON groups. This is a readout-integration wave, not another round of
  research on the brain.
* The eight presentations are repeated measurements of the same learned
  model under different realisations of the stochastic stimulus, aggregated
  and decoded once. Not eight separately trained flies, not an ensemble
  voting. Shiu et al. used Poisson stimuli and multiple simulations per
  condition, which supports sampling as such, not our specific eight trials
  of 20 ms. Six instruments → 48 presentations per round, one decision.
* Largest implementation risk: eight readings must not become an eightfold
  reward. Proposed deltas are computed from the same pre-update state,
  averaged, applied once. Eight copies of the same trace must give the same
  update as one.
* The WAIT margin is in baseline-SD units; replacing a single reading by the
  mean of eight requires a reference measured for k = 8, with stimuli and
  seeds fixed before evaluation, no PnL or desired trade frequency involved,
  versioned and frozen. Eight silent presentations are absence of response;
  present responses balancing near zero may be WAIT. Not the same thing.
* v2 justifies testing the integration, not that it works for any context:
  a further stimulus set fixed before running, with new encoder patterns and
  new seeds, no re-selection after seeing what passed. No profitability
  required; measure readout stability and that both learning paths still work.
* "Real observations" in the Phase One report is ambiguous: historical market
  data or observations actually executed in the simulator? Resolve from the
  artifacts, with counts and origin. The owner presumes neither.
* PPL1 − PAM stays as our experimental convention, but "the only consistent
  sign" is too strong: the reward raising that score does not prove every
  grouped MBON carries that biological valence. Keep observed anatomy,
  biological interpretation and our chosen convention separate.
* The owner is evaluating the report as brought by the reviewer and has not
  run the repository or checked the 150 tests directly.

### Fable addenda (reviewer, 2026-09-11) — binding for the k = 8 wave

1. **Pre-registration rule, unchanged.** The §5 protocol
   (`experiments/k8_readout/PROTOCOL.md`: stimulus set, seed schedules,
   metrics, aggregate status rules, pass/fail) and the §3 baseline procedure
   are committed ALONE, before any k = 8 evaluation or baseline run exists,
   exactly as `b9655ea` and `f63825b`. The hash goes in `results.md`.
2. **Seed policy.** Replicate seed = a declared deterministic function of
   (learned-state digest, observation id, stable instrument id, replicate
   index r ∈ 0..7), e.g. SHA-256 of the tuple truncated to 64 bits. Never the
   candidate's list position, never Python `hash()`. k = 1 mode is replicate
   index 0 of the same schedule, so k = 1 and k = 8 are paired by
   construction. One test permutes candidates and renames tickers and asserts
   an identical DecisionRecord digest.
3. **Clocks.** The experiment clock advances one decision cycle (500 ms) per
   round, not per presentation. The reference transient state is restored
   before each replicate; decay and eligibility time constants act once per
   round. Wall-clock per round is measured separately (§7) and never feeds the
   model.
4. **Aggregate status rules, defaults unless the protocol says otherwise
   before running.** Per replicate: technical failure (exception) aborts the
   round — no DECISION event, one `ROUND_ABORTED` event with the reason;
   INVALID (saturation / non-finite, the existing INVALID_STATE rule) in ANY
   replicate makes the aggregate INVALID, nothing is averaged. Otherwise the
   aggregate is the mean of the eight population rates; aggregate
   NO_RESPONSE iff all eight replicates have zero spikes over the 45 decoder
   MBONs; otherwise VALID, and WAIT iff |V₈| < θ₈. A silent replicate inside
   an active batch contributes zeros. Report NO_RESPONSE with unit =
   candidate evaluation (batch) and, separately, silent replicates with unit
   = presentation.
5. **θ₈ measurement.** The distribution normalised is the k = 8 aggregate
   V at the neutral reference (same reference brain state and neutral
   stimulus as `DECODER.md` §1), across N = 64 batches under a declared seed
   schedule disjoint from every schedule used so far. BASELINE_HZ₈ = its
   mean, θ₈ = 1.0 × its SD; the coefficient stays 1.0. Report next to the
   k = 1 values (−2.3033 / 3.2414). With replicates independent given a
   frozen state the expected SD ratio is about 1/√8 ≈ 0.354; a ratio far
   from it is a finding to report, not to fix. If SD₈ = 0 the wave stops and
   reports; no substitute divisor. The artifact is a versioned file (graph
   sha256, state digest, seed schedule, N, commit) next to the k = 1
   constants, which are kept for the k = 1 mode.
6. **Normalised learning, mechanics.** The DecisionRecord of the selected
   candidate carries the eight eligibility traces (or exactly what the
   stored-trace replay already stores, ×8). At settlement Δ_r is computed for
   each r from the same pre-update W and the same dopamine drive with all
   existing eligibility, compartment and floor rules; Δ = mean_r Δ_r; applied
   once, atomically; one LEARNING event with `k = 8`,
   `normalisation = "mean_of_deltas"`, `eligibility_source =
   "replayed_from_decision"`. The floor is applied per replicate before
   averaging — declared convention, documented. The "eight identical traces ≡
   one" test asserts `allclose(rtol=1e-12)` AND shows that applying the
   single-trace update eight times sequentially gives a larger depression, so
   the test cannot pass vacuously.
7. **Restart mid-batch: deterministic recompute, not resume.** A batch is a
   pure function of (learned-state digest, observation id, seed schedule).
   Nothing is written to the log until the batch completes; per-replicate
   measurements go inside the DECISION record (or in one MEASUREMENT event
   appended in the same atomic write). On restart, an observation with no
   DECISION event is recomputed from scratch and must produce an identical
   DecisionRecord digest — one test kills at replicate 3 of candidate 4 and
   compares with the uninterrupted run. Resume-in-place is not required.
8. **§5 design, bounded.** Contexts: the v2 pair, labelled "selected after
   v1 failed on resolution", plus four new nominal patterns chosen by a rule
   written in the protocol before running (e.g. corners of the declared
   feature range), with pairwise KC Jaccard ≤ 0.368 checked BEFORE the
   evaluation — Jaccard is a stimulus property, selection by it is allowed;
   selection by any readout result is not. New seed schedule disjoint from
   seeds 1–8. Per context 16 batches at k = 8; k = 1 is replicate 0 of each
   batch. Metrics: SD of V across batches (k = 1 vs k = 8); decision
   agreement = fraction of batches equal to the modal decision (k = 1 vs
   k = 8); NO_RESPONSE, silent-replicate, INVALID counts with denominators;
   learning: the §4 v2 appetitive and aversive checks at k = 8 on the v2 pair
   AND on one new pair, plasticity-off exactly 0.000. Pass/fail written
   before running, suggested: SD₈ < SD₁ in ≥ 5/6 contexts, agreement₈ ≥
   agreement₁ in ≥ 5/6, learning sign correct 8/8 seeds on both pairs. A
   failure is reported, never fixed by changing stimuli, gain, θ or k.
9. **Demo.** Re-run the §8 Phase One demo at k = 8 on the same fixture, seeds
   and 320 bars, with the same mid-run restart, and report the same table
   plus per-decision NO_RESPONSE / WAIT / INVALID counts. The k = 1 demo
   numbers already in `results.md` are not re-run except for the §7
   benchmark. Net PnL is not a gate metric.
10. **Provenance.** Resolve "real observations" from the tree: if no CSV
    exists under `data/market/`, say so in one line and label every dataset
    used SYNTHETIC with generator and seeds. No downloads in this wave.
11. **Wording fix.** In `docs/DECODER.md` replace "the only sign consistent
    with depression-only plasticity" with a three-layer statement: observed
    anatomy (innervation split), literature interpretation (assumes hemibrain
    numbering, cell-type valence), our convention (V = PPL1-side − PAM-side).
    One paragraph, no literature audit, decoder unchanged.
12. **Process and cost.** One Opus agent, sequential, one commit per section
    in the order 1 → 2 → 3 → 5-protocol (alone) → 3-baseline → 4 → 5 → 6 → 7
    → 8. `pytest tests/` twice only at close. HANDOFF block ≤ 25 lines. No
    reopening of graph, plasticity fix, gain, window or MBON groups. Compute
    budget: the whole wave's neural simulation should stay within tens of
    minutes on this machine; if a step projects beyond that, cut batches or
    contexts and say so — never cut k. No statistical hunting beyond
    addendum 8.

## D5 / D6 — historical-market integration and local observer — canonical amendment (owner, 2026-09-11, original in English)

D5 APPROVED: KEEP THE CURRENT K=8 MARGIN.
D6 APPROVED: FIRST REAL HISTORICAL-MARKET INTEGRATION.

Read the session log, docs/SPEC.md and the completed D4 artifacts.
Use the repository as the source of truth for truncated
sentences in the pasted report.

NEXT WAVE

Deliver the existing neural trading loop running on actual
historical market data, plus a minimal local observer page.

Do not reopen the scientific core or redesign the product.

PRESERVE

- k = 8;
- gain = 0.10;
- 20 ms presentations;
- current sensory mapping and declared input bounds;
- current MBON membership and decoder convention;
- normalized single learning update per outcome;
- current experiment-clock semantics;
- inventory-aware, long-only paper execution;
- immutable upstream and upstream audit.

No live execution, launch integration, token, fee distribution,
wallet connection or public deployment.

1. D5 — FREEZE THE DECISION RULE

Keep coefficient 1.0 and the existing k=8 baseline artifact.

Load the exact stored values. Do not replace them with rounded
numbers copied from the report.

Do not recalibrate the baseline or tune the margin using
historical returns, trade frequency or preferred behavior.

Describe the margin as an action-decoding rule, not a probability
of financial success.

Report empirical action/status frequencies:
- per candidate;
- per decision round;
- after inventory/execution constraints.

Do not assume a Gaussian 31.7% crossing rate applies to the
actual decoder distribution or to multi-candidate selection.

Correct the SD-ratio wording to "compatible with sampling
variation" unless stronger evidence already exists.
No additional research phase is required for this wording.

2. D6 — DATA ACQUISITION

Authorized source:
Kibot public free intraday samples.

Source page:
https://www.kibot.com/free-historical-intraday-data.html

Verified download links at the time of this instruction:

IBM, unadjusted:
https://api.kibot.com/?get=e4Vuqcxk

OIH, unadjusted:
https://api.kibot.com/?get=NaatWNJD

Format documentation:
https://www.kibot.com/file-format/data-format-reference.html

Download only these two datasets for this wave.
No paid API, account creation or subscription.

Store raw files under gitignored data/market/.
Record source URL, retrieval time, file hash, byte size,
instrument, adjustment status and observed date coverage.

Validate that the current source page still identifies these
links as the intended unadjusted instruments.

The sample links may change over time. Do not substitute a
different instrument or adjusted dataset silently.

If access or coverage fails, report the exact acquisition
blocker and complete the importer/tests without fabricating
historical results.

These files are internal-use inputs, not public repository
fixtures or files to redistribute with the application.

Use two real instruments in this run.
Retain configurable support for six; do not duplicate or
rename series to manufacture six historical instruments.

3. DATA AND TIME SEMANTICS

Label this dataset HISTORICAL_MARKET.
Keep it distinct from all existing SYNTHETIC fixtures.

Parse the vendor's headerless OHLCV format explicitly.
Interpret timestamps in America/New_York and store canonical
timestamps in UTC.

Kibot minute timestamps identify bar opening time.

Represent bar_start, bar_end and observation availability.
Final OHLCV values are unavailable before bar_end.

Use native one-minute bars for this integration.
Do not manufacture intrabar paths from OHLC values.

Validate:
- schema and numeric values;
- positive prices and valid OHLC relationships;
- timestamps, duplicates and ordering;
- per-instrument/session coverage;
- missing intervals.

A missing minute is not automatically a corrupt dataset:
the vendor omits intervals without reported trades.

Do not silently compress missing time or forward-fill
executable prices.

Use elapsed market time for outcome horizons, not row count.

Separate DATA_GAP / STALE_DATA / WARMUP from neural NO_RESPONSE
and from valid neural WAIT.

Normalization must use available past/current observations
only, never the full dataset or future evaluation period.

Report clipping, saturation and silence under the existing
encoder bounds. Do not automatically widen those bounds
because historical results look bad.

4. FIXED HISTORICAL PROTOCOL

Requested date range, inclusive:
2026-08-03 through 2026-09-04.

Use regular-session observations only.

Partitions:

WARMUP:
2026-08-03 through 2026-08-14.
Populate causal market-feature history.
No trading reinforcement.

LEARNING:
2026-08-17 through 2026-08-28.
Run the complete sequential decision/outcome/learning loop.

FROZEN EVALUATION:
2026-08-31 through 2026-09-04.
Evaluate the learned checkpoint on later market observations.
Disable synaptic learning and forgetting in this evaluation.

Preserve transient neural simulation during frozen evaluation.
"Frozen" means learned weights do not change.

Start from a declared clean reference brain checkpoint,
not a checkpoint trained on the previous odor demonstrations.

Commit the experiment configuration and seed schedules before
running the historical experiment.

Preserve the current documented paper-execution defaults:
sizing, costs, delay and horizon. Record their exact values
and units before the run.

If a field was previously defined only in synthetic steps,
define its historical-time interpretation explicitly before
execution. Do not choose it by inspecting PnL.

Do not cross date partitions with unresolved trades.
Use declared session/partition boundaries for entry eligibility,
not advance knowledge of future prices or data gaps.

Do not reshuffle dates or replace losing periods.

5. EXECUTION AND OUTCOME INTEGRITY

Maintain the existing execution delay, measured from
observation availability, not from the bar-open timestamp.

No same-bar hindsight execution.
No order may use a future high, low or closing price as
information available when the decision was made.

Document the paper-fill assumption.
These are simulated executions, not observed exchange fills.

If a due fill or settlement lacks a valid price, represent
the pending/delayed/failed state explicitly under a fixed rule.

Do not invent a fill or silently drop an unfavorable episode.

Keep BUY, inventory-reducing SELL, WAIT, policy rejection
and POLICY_CLOSE distinct.

State whether each cost is charged per execution or per
round trip. Do not accidentally charge a round-trip parameter
twice.

Reconcile:
gross realized PnL - fees - modeled slippage = net realized PnL.

Reward/punishment uses the existing net-outcome rule.
Preserve one normalized learning event per settled episode.

Maintain checkpoints and restart protection around both
execution and learning.

6. SMALL COMPARISON, NOT AN OPTIMIZATION PROJECT

During frozen evaluation, also run an untrained reference
with the same market observations, baseline and paper policy.

Use separate accounting and immutable identities.

For the paired comparison, use common exogenous random
streams keyed to observation, instrument and replicate.

The comparison random schedule must not change merely because
the learned weights differ. A seed derived from the weight
digest would change the stimulus realization between branches.

Version this comparison schedule explicitly. Preserve the
original D4 seed policy and artifacts as historical regression
evidence.

Report both branches without choosing a winning seed.

Compare:
- neural response/status distributions;
- action frequencies;
- completed trades and exposure;
- gross and net results;
- behavior by instrument.

The untrained comparison is not a full test against chance.
Do not claim trading skill from one short historical run.

No profitability requirement is part of the engineering gate.

7. MINIMAL LOCAL OBSERVER — SEPARATE PRESENTATION LAYER

After the historical loop is connected, provide a simple
local read-only observer using the existing event stream.

This is not the public launch frontend.
Do not build accounts, payments, chat, social automation,
a marketplace or a new deployment stack.

The page must show:
- HISTORICAL REPLAY / PAPER status;
- historical market timestamp and replay speed;
- instrument/context currently being presented;
- encoded sensory channels;
- actual measured neural readout;
- selected instrument and action;
- current paper position;
- realized outcome and reinforcement event;
- paper cash/equity and cumulative realized PnL;
- counts of completed trades, WAIT and NO_RESPONSE.

Use actual logged/runtime telemetry.
Do not invent individual-neuron spikes when only population
rates were recorded.

Read the same canonical events used by the backend.
The frontend must not recalculate trading decisions or PnL.

Pause/speed controls affect playback only.
They must not change brain time, seeds, choices, learning
or the canonical event log.

Show the historical result only when playback reaches its
event time. Do not expose a later outcome beside an earlier
decision.

Bind locally. No public ingress or public dataset exposure.

A functional chronological observer is sufficient.
Do not delay the historical integration for visual polish.

8. TESTS AND DELIVERY

Extend the existing suite with:
- actual vendor-format parsing;
- bar-open versus availability semantics;
- missing intervals without time compression;
- causal feature normalization;
- historical delay and horizon semantics;
- partition boundaries;
- frozen evaluation with unchanged learned weights;
- duplicate-outcome/restart protection on historical replay;
- observer event-order and accounting consistency.

Use small synthetic/vendor-shaped fixtures for committed tests.
Keep downloaded market data outside Git.

Deliver:
- data manifest and coverage report;
- fixed experiment configuration;
- runnable historical loop;
- beginning/end checkpoint hashes;
- historical event log;
- learned-versus-reference comparison;
- gross/net accounting breakdown;
- local observer and exact startup command;
- tests and exact outcomes;
- commits, tree status and updated the session log.

Preserve failed runs and their explanations.
A retry after a software correction must have a new run ID.

Do not claim completion because the importer returns rows.
Show actual market context passing through the existing
sensory/neural/decision/outcome/learning chain.

If historical inputs produce only silence, invalid states
or no completed learning episodes, report that limitation.
Do not insert a heuristic trader or alter thresholds to
manufacture a demonstration.

Conclude separately:
A. Historical-data integration status.
B. Observed neural/learning behavior on that data.
C. Local observer status.

Run the complete regression gate twice at closure.
Stop at the closing report.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* D4 closed on the report. D5 = option (a): θ = 1 × SD₈ with the baseline
  already produced, no recalibration after looking at trades; gain, MBONs,
  encoder and the eight presentations stay frozen. The margin is a rule that
  turns neural activity into action, not confidence that a trade will work;
  it is not to be made more conservative now, nor searched for the number
  that produces the best result.
* Wording: ≈ 31.7 % outside ±1 SD is a property of the normal distribution,
  not a guaranteed rate of this circuit; and with several candidates compared
  and one chosen, the round's action frequency is not the per-candidate
  frequency. Measure, do not presume. "0.314 vs 0.354 is sampling error"
  becomes "compatible with sampling variation; the results do not establish
  another cause". Wording only, not a reason for another wave.
* D6 source: Kibot public free samples, IBM and OIH, one-minute bars,
  unadjusted, available without registration. The owner opened the files:
  intraday, the consulted versions reach September 2026. Two instruments in
  this first historical run, capacity for six retained; this is not the
  final portfolio — it replaces invented instruments with real series while
  preserving selection among candidates.
* Dates 2026-08-03 → 2026-09-04, split into measurement warm-up, learning
  and later evaluation, are the owner's operational choice, not chosen by
  the fly's performance.
* Two vendor details must enter the adapter: the bar timestamp marks its
  open, so a 09:30 bar's final values enter an observation only after that
  minute ends; minutes without trades may be omitted, so "five rows later"
  is not "five minutes later", and no execution price is invented to fill a
  gap.
* Samples stay in local storage outside Git; the observer is local too —
  the sample licence is internal use, not public redistribution.
* The observer shows historical context → sensory stimulus → neural
  response → decision → simulated trade → outcome → weight change, with the
  historical time visible and the label "HISTORICAL REPLAY · PAPER". A
  replay is never presented as a live feed.
* The owner is not recertifying the 194 tests; they are evaluating the
  closing brought by the reviewer.

### Fable addenda (reviewer, 2026-09-11) — binding for the historical wave

1. **Pre-registration, same rule.** `experiments/historical/PROTOCOL.md` and
   `experiments/historical/config.json` (partitions, seed schedules including
   the comparison schedule, execution defaults with units and their
   historical-time interpretation, entry-eligibility and session-close
   rules, the full status taxonomy, pass conditions for "context passes
   through the chain") are committed ALONE before any historical run. The
   data manifest may precede them. A run started before that commit is
   discarded and said so.
2. **Acquisition record.** Fetch the source page and the format reference
   first; quote in the manifest the vendor's sentence on timestamp
   semantics and on omitted minutes. Then the two links, with sha256,
   bytes, row count, first and last timestamp, whether extended hours are
   present, and coverage per regular-session day inside the window (rows
   per day, missing minutes per day). Append to `data/MANIFEST.md`. If
   coverage inside the window is partial, use what exists and report; never
   shift the dates. If the network is unavailable to the agent, report the
   exact blocker, finish the importer on vendor-shaped fixtures, and stop.
3. **Cadence and clocks.** One decision round per regular-session minute
   bar, at that bar's `bar_end` (09:30 ≤ bar_start < 16:00 America/New_York).
   The brain clock advances one decision cycle per round exactly as in D4;
   market time and brain time are two clocks, both in every DECISION event.
   Decay and eligibility act per round, in brain time — declared, not
   re-derived. WARMUP runs features only: no neural simulation, no DECISION
   events, one `WARMUP` status per observation.
4. **Execution in historical time, defaults preserved.** Observation at
   `bar_end(t)`. Fill at the open of the first available regular-session bar
   with `bar_start ≥ bar_end(t)`; if that bar is not the next calendar
   minute, the fill carries `DELAYED_FILL` with elapsed market minutes.
   Horizon H = H market minutes from the fill's `bar_start`; settlement at
   the open of the first available bar with `bar_start ≥ fill + H`, flagged
   likewise if delayed. Entry eligibility is a clock rule:
   `bar_end + 1 min + H ≤ 16:00` on the same session. A position still open
   at the day's last regular-session bar (reachable only through gaps) is
   closed by `POLICY_CLOSE` at that bar's close with `SESSION_CLOSE_FILL`,
   counted separately. Nothing therefore crosses a day or a partition. Fee
   and slippage: one line in config stating per-execution or per-round-trip.
5. **Seeds.** LEARNING uses the D4 seed policy unchanged (digest-keyed).
   FROZEN EVALUATION uses `comparison_v1`, keyed to (observation id,
   instrument id, replicate), identical in the learned and the reference
   branch. Both named in config before running. The reference branch is the
   clean reference checkpoint (graph sha256 + zero learned gains, hash
   recorded) with learning and forgetting off.
6. **Frozen semantics.** Learning and forgetting off, transient simulation
   on, eligibility may accumulate and is never applied. OUTCOME events are
   emitted and settled for accounting; no LEARNING event is written, the
   settlement counter records `SETTLED_FROZEN`. The end-of-partition
   checkpoint hash of the learned branch must equal its start hash.
7. **Encoder risk, declared.** One-minute returns are far smaller than the
   synthetic fixture's; the causal normaliser is warmed by WARMUP and may
   still leave most observations near neutral or clipped. Report the
   clipping / silence / INVALID rates per partition and per instrument and
   stop there. Widening bounds, changing gain or θ is out of this wave.
8. **Observer, bounded.** `observer/index.html` (vanilla JS, no framework,
   no build step, no npm) served by `observer/serve.py` (stdlib
   `http.server`, bound to 127.0.0.1) together with the run's event log.
   Playback is an event-index cursor; speed and pause move the cursor only.
   Cash, equity and PnL come from event fields the backend already emits or
   adds in this wave (an `ACCOUNT` field on OUTCOME is enough); the page
   counts statuses and never sums money. Population rates and statuses per
   replicate and aggregate, as recorded, nothing per neuron. The agent
   verifies it in a headless browser by stepping to a known event and
   comparing the displayed fields with the log — text in the report, no
   screenshots. Exact startup command in HANDOFF.
9. **Compute budget, estimated before running.** 2 instruments × 8 = 16
   presentations per round ≈ 0.4 s; LEARNING ≈ 3,900 rounds ≈ 26 min;
   FROZEN ≈ 1,950 rounds × 2 branches ≈ 26 min; WARMUP ≈ 0. If the estimate
   exceeds 90 min, reduce by a rule written in the protocol before running
   (never after), and never by reducing k. Run the experiment in the
   background while building the observer.
10. **Tests.** Vendor-shaped fixtures of at most a few hundred rows,
    generated by a committed script, covering: a gap, a duplicate, an
    extended-hours row, a session end with an open position, and a partition
    boundary. Downloaded data never enters a test. Restart test on
    historical replay uses the D4 fault-injection pattern.
11. **Commit order and process.** 1 (wording + margin freeze) → 2
    (acquisition + manifest) → 3 (importer + time semantics + tests) →
    4-protocol (alone) → 5 (historical execution semantics + tests) → 4-run
    (results, checkpoint hashes, event log) → 6 (comparison) → 7 (observer)
    → 8 (HANDOFF). One Opus agent, sequential. `pytest tests/` twice only at
    close. HANDOFF block ≤ 25 lines. No reopening of graph, plasticity fix,
    gain, window, MBON groups, θ or baseline.

## D7 — WARMUP-selected horizon and context discrimination — canonical amendment (owner, 2026-09-11, original in English)

D7 — WARMUP-SELECTED HORIZON AND CONTEXT DISCRIMINATION

D7(a) IS APPROVED.

This is the next bounded wave after the completed historical
integration and observer. It is NOT a repeat of Phase One.

Read the session log, docs/SPEC.md, the hist-003 configuration,
data manifest and historical execution implementation.

Confirm the latest accepted repository state before changes.
Preserve all completed waves and their original results.

OBJECTIVE

Select a fixed holding horizon using only a new WARMUP period,
then test whether training changes context discrimination,
rather than merely suppressing BUY everywhere.

Do not define success as profitability, more BUY actions,
more reward events or a preferred reward/punishment balance.

1. FROZEN COMPONENTS AND SCOPE

Preserve:
- k = 8;
- gain = 0.10;
- 20 ms neural presentations;
- existing encoder mapping, normalization algorithm and bounds;
- MBON membership and decoder sign convention;
- the existing k=8 baseline and margin coefficient;
- normalized single learning update per outcome;
- episode-specific credit assignment;
- market/brain clock semantics;
- long-only inventory-aware execution;
- position sizing, fees and modeled slippage;
- execution-delay and session-boundary rules.

The permitted behavioral parameter change is the fixed H
selected by the rule below.

Do not change SELL into SHORT.
Do not disable early neural SELL decisions to improve results.
Do not alter the reward rule or reward only gross PnL.
Do not reduce costs to manufacture positive reinforcement.

Use IBM ONLY for this experiment.

Keep multi-instrument support intact. OIH is excluded from
this wave because of the previously reported availability
problem, not because of its returns.

No new provider, paid data, live execution, wallet, token,
economic integration or public deployment.

Reuse the existing local observer. No frontend redesign.

2. FIXED DATA WINDOW AND PARTITIONS

Reuse the existing, hashed, unadjusted IBM Kibot file.
Do not replace it with a newly downloaded rolling sample.

Local market timezone: America/New_York.
Canonical stored timestamps: UTC.

New experiment window:
2026-06-15 through 2026-07-31, inclusive.

WARMUP:
2026-06-15 through 2026-07-02.
13 scheduled regular sessions, excluding June 19.

LEARNING:
2026-07-06 through 2026-07-17.
10 scheduled regular sessions.

FROZEN:
2026-07-20 through 2026-07-31.
10 scheduled regular sessions.

July 3 is a market holiday.
Use the established regular-session calendar.

No observations from 2026-08-03 through 2026-09-04 may enter:
- feature initialization;
- H calibration;
- learning;
- evaluation;
- baseline recalibration.

Start from the declared clean reference brain checkpoint,
not from hist-003 or an odor-trained demonstration checkpoint.

Initialize causal market-feature state from this new window.

The design is informed by hist-003, but the numerical
calibration and evaluation use disjoint dates. Describe this
as a revised historical experiment, not prospective evidence.

Validate local coverage before running.

Missing coverage is a reported blocker, not permission to
choose different dates after inspecting outcomes.

3. PREREGISTRATION AND WARMUP REQUIREMENTS

Before computing horizon statistics, commit a D7 protocol
and configuration containing:
- these dates and instruments;
- candidate horizons;
- the calibration formula;
- cost conventions;
- data-quality criteria;
- training and comparison seed policies;
- primary and secondary metrics;
- evaluation sufficiency rules.

After WARMUP calibration, commit the selected H and its
calibration artifact before any LEARNING/FROZEN neural run.

WARMUP performs feature initialization and calibration only.
No neural trading reinforcement occurs during WARMUP.

Require at least 10 qualifying WARMUP sessions.

A qualifying session must have:
- at least 95% of scheduled one-minute bars;
- valid, deduplicated OHLCV;
- at least 100 usable common calibration origins.

Eligibility for this requirement is based on data quality,
not volatility, profitability or reward balance.

Use all qualifying sessions in the fixed WARMUP window.
Do not cherry-pick ten of them.

If fewer than ten qualify, report INSUFFICIENT_WARMUP.
Do not extend dates, relax criteria or substitute instruments.

4. EXACT HORIZON-SELECTION RULE

Candidate holding horizons, in elapsed market minutes:

H_SET = [8, 15, 30, 60, 90, 120]

Determine C, the round-trip cost in basis points, from the
existing execution configuration.

Use a flat-price round trip at the configured notional to
measure the combined effect of existing fees and modeled
slippage. Record per-leg and round-trip conventions.

Do not infer C from rounded report text.
Do not reinterpret a round-trip charge as a per-leg charge.

For every qualifying WARMUP session, build a common set of
decision origins usable for every candidate horizon.

An origin must:
- have causally available market features;
- permit the existing entry delay;
- permit the maximum candidate horizon within the session;
- have the required observed entry/exit prices.

Use the same origin set across H values within a session.

For each origin t and candidate H, compute:

g(t,H) = gross fixed-hold long return, in basis points,

using the established entry/exit price and timing convention,
before deducting costs.

All prices used in these calibration returns must lie inside
WARMUP and the same session.

Define:

A(H) = median across sessions of
       [median across common origins of abs(g(t,H))]

Select:

H* = the smallest H in H_SET for which A(H) >= 2 * C.

This is a fixed movement-versus-cost operating rule.
It is NOT a forecast of profitability or proof that returns
are predictable.

Do not select H by:
- strategy PnL;
- mean signed return;
- win rate;
- reward balance;
- decoder output;
- LEARNING or FROZEN results.

Do not interpolate horizons or try additional multipliers.

If no candidate qualifies:
- report NO_HORIZON_MEETS_RULE;
- deliver the calibration table and implementation/tests;
- do not silently choose H=120 or lower the multiplier;
- do not start a claimed successful D7 learning experiment.

Freeze H* for all subsequent D7 runs.

5. LEARNING RUN AND ACTUAL OUTCOMES

Run the existing chronological paper-learning loop on the
LEARNING partition with H*.

Use one preregistered training seed schedule for this wave.
Do not search multiple training seeds and retain a winner.

Only actual settled paper episodes generate reinforcement.
No rewards for unchosen actions or hypothetical probe trades.

Preserve session boundaries and the existing handling of
delayed/missing fills.

Do not compress missing clock time.
Do not use a bar's completed OHLCV at its opening timestamp.

Do not change the fill timing while changing H.
Print the actual observation-availability → fill delay in
the report so off-by-one timing cannot remain hidden.

Report:
- completed episodes;
- gross/net PnL and costs;
- reward, punishment and neutral counts;
- actual holding-duration distribution;
- neural SELL, POLICY_CLOSE and session-close counts;
- invalid states, WAIT and NO_RESPONSE.

H is a maximum/fixed policy horizon under the existing
execution semantics, not a guarantee that every neural trade
will last H minutes.

If early SELL decisions keep actual exposure much shorter
than H*, show that explicitly. Do not suppress those decisions.

Use new run identities and preserve failures.
Do not retrospectively modify hist-003.

6. FROZEN COMPARISON AND COMMON PROBE GRID

Evaluate two fixed checkpoints on FROZEN:

TRAINED:
The final D7 LEARNING checkpoint.

REFERENCE:
The clean reference checkpoint without reinforcement training.

Disable both learning and forgetting in FROZEN.
Verify unchanged learned-state hashes.

Use identical causal market observations and common exogenous
random streams for both branches.

Reuse comparison_v1 or its verified equivalent:
seeds must not depend on the checkpoint's weight digest.

Maintain separate paper accounts.
Actual trades remain subject to inventory and execution rules.

In addition, record a read-only neural probe at each eligible
one-minute decision origin, regardless of whether the paper
account is already holding a position.

A probe records the continuous pre-threshold decoder score,
status and timestamp from the same fixed brain.

This diagnostic must not:
- modify weights or eligibility used by real decisions;
- place orders;
- generate reinforcement;
- alter the experiment clock;
- provide future information to the encoder or brain.

Reuse the ordinary candidate readout where semantically
identical; do not duplicate neural work unnecessarily.

The common probe grid is determined by:
- the session calendar;
- causally available features;
- entry-delay rules;
- room for H* before session end.

It must NOT depend on:
- which branch bought;
- whether the later outcome is profitable;
- inventory;
- score sign or magnitude.

After recording scores, attach an evaluator-only label:

G(t) = net return of a hypothetical fixed-notional LONG
       entered under the existing fill convention and held
       for H*, including unchanged costs.

Y(t) = 1 when G(t) > 0; otherwise 0.

Use one common G(t) for both branches.

These labels measure fixed-horizon entry-context quality.
They do not measure the quality of every possible exit action.

They are analysis-only counterfactuals:
- no learning events;
- no changes to the paper bankroll;
- no summing overlapping probes into an executable PnL.

Missing future prices create UNAVAILABLE_LABEL, with explicit
counts. Never invent fills or replace an unavailable label
with a loss.

Keep future labels in the evaluator only.

7. PRIMARY CONTEXT-DISCRIMINATION METRIC

Use the continuous score whose larger values favor BUY,
before thresholding and before inventory constraints.

Do not use the BUY flag itself as the primary score.

For each FROZEN session with at least:
- 10 profitable probe labels;
- 10 nonprofitable probe labels;

compute ROC-AUC separately for TRAINED and REFERENCE.

Use the standard pairwise definition:

AUC = probability that a profitable context has a higher
      score than a nonprofitable context,
      with ties receiving 0.5 credit.

Primary metric:

DELTA_AUC = mean across qualifying sessions of
            [AUC_TRAINED - AUC_REFERENCE]

Give qualifying sessions equal weight.
Also report both mean AUC levels and every session's result.

Require at least five qualifying sessions for an aggregate
context-discrimination conclusion.

A constant score has AUC 0.5 when both classes exist.
A one-class session has undefined AUC, not AUC 0.5.

Keep technically successful silent responses in the analysis
using their actual finite readout. Preserve NO_RESPONSE as
a separate status; do not drop silent contexts to improve AUC.

For technical failures or invalid/saturated states:
- report per-branch and paired coverage;
- disclose all exclusions;
- use the same paired set for both AUCs.

If either branch or the paired set covers less than 95% of
otherwise label-available probes, mark the aggregate inference
as coverage-limited/inconclusive.

Required metric tests:
- subtracting a constant from every reference score does not
  improve AUC;
- positive uniform rescaling does not improve AUC;
- constant scores give 0.5 when both classes exist;
- perfect and reversed rankings behave correctly;
- ties and missing classes are handled explicitly.

This prevents blanket inhibition from being counted as
improved context ranking.

8. SECONDARY CHECK AT MATCHED PARTICIPATION

Within each session, select the highest-scoring 20% of probes
for each branch independently.

Compare their mean G(t) and profitable-label rate.

Both branches select the same fraction, so "buying less"
cannot explain an advantage in this diagnostic.

Handle boundary ties by fractional weighting.
Do not use future labels or time order to break score ties.

Keep 20% fixed. Do not search for the best percentile.

This is a retrospective ranking diagnostic, not a new trading
policy and not a backtested executable portfolio.

Report actual BUY/SELL/WAIT frequencies separately.

A useful score ranking with almost no executable BUY actions
must not be described as profitable trading behavior.

9. DEPENDENCE, UNCERTAINTY AND CONCLUSIONS

Overlapping H-minute outcomes are not independent trials.

Report:
- unique sessions;
- probe counts and class counts;
- actual completed trade counts;
- per-session effects.

Provide a paired session-resampling uncertainty summary for
DELTA_AUC:
2,000 bootstrap draws of whole qualifying sessions,
with a preregistered seed and both branches kept paired.

Describe it as limited, day-resampled uncertainty conditional
on this training run, not a definitive significance test.

Do not bootstrap individual minute rows as independent data.

Distinguish conclusions:

A. Context-discrimination evidence in this experiment:
   improved within-session ranking relative to the reference,
   considered alongside trained AUC level, uncertainty,
   coverage and matched-participation results.

B. Suppression without demonstrated discrimination improvement:
   lower BUY frequency without supported improvement in
   context ranking.

C. Inconclusive:
   too few informative sessions, inadequate coverage,
   unstable effects or uncertainty that does not resolve
   the question.

Positive DELTA_AUC alone is insufficient if TRAINED remains
at or below chance-level ranking.

Do not equate failure to demonstrate discrimination with
proof that this system can never learn any market structure.

Do not require a positive scientific outcome for engineering
completion.

10. GUARDS, OBSERVER AND DELIVERY

Add focused tests proving:
- changing LEARNING/FROZEN prices cannot change H selection;
- calibration never accesses prices outside WARMUP;
- all H candidates use the declared common origins;
- changing evaluator labels cannot change neural scores;
- probes cannot mutate learning, accounts or decisions;
- FROZEN weights remain unchanged;
- overlapping hypothetical probes are not booked as trades;
- restart cannot duplicate outcomes or learning.

Reuse the local observer to display the new run.

Add only:
- selected H and calibration provenance;
- actual versus hypothetical/probe labels;
- current phase and historical timestamp;
- final context-discrimination summary after evaluation.

Do not reveal a future probe label during earlier playback.
Do not build a new frontend.

Deliver:
- preregistration commit;
- data and coverage manifest;
- full A(H) calibration table and H* artifact;
- checkpoint hashes;
- chronological actual-trading log;
- paired frozen probe dataset;
- per-session AUCs, DELTA_AUC and uncertainty summary;
- matched-participation comparison;
- reward counts, holding durations and cost breakdown;
- tests, exact commands, commits and clean-tree status;
- updated the session log with separate engineering and
  experimental conclusions.

Run the full regression gate twice at closure.
Repeated deterministic runs are not independent experiments.

If the calibration rule fails, close with that bounded result.
Otherwise complete LEARNING, FROZEN and the report.

Do not expand into another parameter search, another
instrument or another date window in this session.

Implement D7 only and stop at its closing report.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* The three decisions closed: IBM alone in this wave; the horizon chosen
  exclusively on WARMUP; an evaluation that measures whether the fly
  distinguishes contexts, not only whether it buys less. OIH stays
  available in the system and is out of this comparison because of the
  reported gaps.
* Window 2026-06-15..07-31, no overlap with the previous experiment; 13
  scheduled sessions for WARMUP, 10 LEARNING, 10 FROZEN, allowing for the
  June 19 and July 3 closures. Effective coverage is to be checked in the
  local file already downloaded.
* The important change in the evaluation is to use the continuous neural
  signal before it becomes BUY/SELL/WAIT. ROC-AUC accepts such a score with
  no conversion to a probability or a binary action. The comparison asks
  whether, after training, contexts that end positive receive relatively
  higher scores than those that end negative. Reducing all responses
  equally earns no credit for discrimination. The hypothetical outcomes
  used in that measurement stay outside learning: no reward for operations
  the fly did not make.
* This wave separates two things hist-003 mixed: the fly becoming less
  inclined to act, and the fly ranking contexts better. The first already
  appeared; the second is what is measured now.

### Fable addenda (reviewer, 2026-09-11) — binding for the D7 wave

1. **Facts the amendment assumes, verified in the tree.** Timestamps are
   already UTC epoch seconds on an America/New_York session grid
   (`flytrade/historical.py:42,143`): no clock migration, "canonical UTC"
   is satisfied as-is. The exit convention is already fixed by D5/D6
   addendum 4: entry at the open of the first available bar with
   `bar_start ≥ bar_end(t)`, horizon exit at the open of the first
   available bar with `bar_start ≥ fill_bar_start + H`. `g(t,H)`, `G(t)`
   and the `POLICY_CLOSE` fill use ONE function with three callers, and one
   fixture test proves the three agree, including through a missing exit
   bar (calibration: origin excluded from the common set; label:
   `UNAVAILABLE_LABEL`; execution: `DELAYED_FILL` as today — three
   declared behaviours of the same convention, not three conventions).
2. **C.** Config says fee 5 bps + slippage 5 bps per execution, so 10 bps
   per leg and C = 20 bps, 2C = 40 bps. The agent measures it anyway by
   one flat-price round trip through `HistoricalExecution` at notional
   1,000 and the measured figure governs; per-leg and round-trip lines
   both appear in the H* artifact.
3. **Probes are the ordinary readouts, extracted after the run.**
   `experiments/historical/run.py:278` evaluates the held symbol every
   round while holding, so with IBM alone every round already carries one
   readout under `comparison_v1` seeds. The probe dataset is built by a
   read-only evaluator over the two FROZEN event logs plus the price file,
   after both branches have finished. No runtime hook, no second neural
   pass. The "cannot mutate" guards are then structural: the evaluator
   opens the logs read-only and imports nothing from `runner`, `mushroom`
   or `execution`; one test proves its score for a round equals the
   DECISION event's score byte for byte, and one test proves the actual
   trade count and the account digest are unchanged by running it.
4. **Score.** The probe score is the decoder's continuous V recorded in the
   DECISION event, for status `VALID` or `NO_RESPONSE`. If the decoder
   records no V on `NO_RESPONSE`, the evaluator computes it by the frozen
   formula from the recorded per-replicate rates (all zero, so
   V = −BASELINE_HZ₈ at full artifact precision) and the protocol says so
   before any run. `INVALID_STATE`, `DATA_GAP`, `STALE_DATA`, `WARMUP` are
   exclusions, counted per branch; the paired set is the intersection.
5. **Probe grid, evaluator-side and branch-blind.** Rounds whose
   observation status is `OK`, whose features are past the per-session
   warm-up, and which satisfy the existing clock rule with H*
   (`historical.py:791`: `(m+1)+1+H* ≤ 390`). The grid is computed from
   the calendar and the price file only, before either log is read; one
   test proves it is identical for both branches.
6. **Calibration origins.** Same clock rule with H = 120, plus observed
   open prices at fill and at fill+H for all six H (the common set).
   Median across origins, then median across sessions, exactly as written;
   the table also reports A(H) per session and the origin count per
   session. Calibration reads rows whose session date lies in WARMUP and
   nothing else; the §10 guard is a fixture copy of the file with every
   non-WARMUP price perturbed, which must give the same H*.
7. **Expected consequence, stated before running.** hist-003 exited 34 of
   37 episodes by neural SELL. If that repeats, actual exposure stays one
   or two minutes whatever H* is, and the LEARNING reward distribution is
   nearly hist-003's. The report therefore cross-tabulates exit reason ×
   reward sign × holding minutes so the reader can see whether H* bound at
   all. That is a finding; nothing is changed to make H* bind.
8. **Per-session AUC gate.** With H* ≤ 120 the grid ends near 13:58 and a
   session has ≈ 250 probes; the ≥ 10-per-class rule is expected to hold
   and is not assumed. Sessions failing it are listed with their class
   counts; the five-session minimum stands as written.
9. **Compute budget.** 1 instrument × 8 = 8 presentations per round
   ≈ 0.2 s (hist-003: 0.41 s per two-instrument round); LEARNING ≈ 3,900
   rounds ≈ 13 min; FROZEN ≈ 3,900 rounds × 2 branches ≈ 26 min;
   WARMUP and calibration ≈ seconds; bootstrap seconds. ≈ 40 min neural in
   total, run in the background while the evaluator is written. If the
   estimate exceeds 90 min, reduce by a rule in the protocol before
   running, never by reducing k.
10. **Seeds and checkpoints.** LEARNING = the D4 digest-keyed policy
    unchanged; FROZEN = `comparison_v1` unchanged; bootstrap seed = one
    declared integer in config. Clean reference = graph sha256 + zero
    learned gains, hash re-derived at start-up as in hist-003 and compared
    with `ba95b605…`.
11. **Coverage first, dates never move.** Before the protocol commit,
    append to `data/MANIFEST.md` the IBM coverage per session for
    2026-06-15..07-31: rows, missing minutes, first and last bar, and an
    early-close check. A session absent from the file or an early close is
    reported where it falls; the WARMUP qualifying count follows the
    committed rule and `INSUFFICIENT_WARMUP` stops the wave as written.
12. **Commit order and process.** 1 coverage manifest → 2 calibration
    module + evaluator + metric tests on fixtures (AUC properties, ties,
    grid, the one-function agreement of addendum 1) → 3 PROTOCOL + config
    ALONE → 4 calibration run and the H* artifact, alone → 5 LEARNING run
    → 6 FROZEN, both branches → 7 evaluator run (probe dataset, per-session
    AUCs, DELTA_AUC, bootstrap, matched participation) → 8 observer
    additions → 9 HANDOFF. One Opus agent, sequential. `pytest tests/`
    twice only at close. HANDOFF block ≤ 25 lines with engineering and
    experimental conclusions apart, the experimental one classified A, B
    or C exactly as §9 defines. Nothing reopened: graph, plasticity fix,
    gain, window, MBON groups, θ, baseline, encoder, k.

## D8 — bounded input and target-alignment diagnostic — canonical amendment (owner, 2026-09-11, original in English)

D8 APPROVED — BOUNDED INPUT AND TARGET-ALIGNMENT DIAGNOSTIC

Read the session log, the D7 protocol/configuration, calibration,
probe artifacts and actual episode log.

This wave is evaluator-only. Do not repeat Phase One or D7.

OBJECTIVE

Determine whether limited, explicitly specified diagnostic
methods can extract predictive ranking from the available
market features or their encoded sensory representation.

Also quantify the mismatch between actual learning outcomes
and D7's fixed-90-minute evaluation target.

D8 is not a proof that information exists or does not exist
for every possible learner.

1. SCOPE AND IMMUTABILITY

No new market-neural runs.
No brain retraining or checkpoint modification.
No parameter search.

Preserve:
- k, gain, neural window and baseline;
- encoder, decoder and learning rule;
- H = 90 minutes;
- costs, sizing, execution and early-SELL semantics;
- existing datasets, dates and run identities;
- upstream and its audit.

No new data download, instrument, frontend, venue or token.

Existing regression tests may run unchanged. Do not launch
new full-connectome experiments to generate D8 measurements.

Use the existing local data and logs. Deterministic feature
and sensory-encoder reconstruction is permitted without
running the neural simulator.

2. CORRECT THE INFERENCE BOUNDARIES

Record explicitly:

- An untrained brain near AUC 0.5 does not establish that
  its inputs contain no predictive information.

- Univariate AUCs near 0.5 do not exclude joint interactions
  or non-monotonic relationships.

- PC1 maximizes represented variance, not predictiveness.
  A nonpredictive PC1 does not establish a nonpredictive
  complete sensory representation.

- Failure of the diagnostic models below is evidence about
  these models, data and target, not a universal input ceiling.

- D7 measured fixed-90-minute context ranking, while actual
  learning outcomes followed earlier neural exits.

Do not rewrite D7 as a success. Preserve its conclusion:
suppression without demonstrated improvement on its metric.

3. REGISTER THIS ANALYSIS BEFORE COMPUTING NEW RESULTS

Commit a D8 analysis plan containing:
- artifact hashes and exact source partitions;
- feature/representation schemas;
- preprocessing rules;
- model parameters;
- seeds;
- metric and coverage rules;
- allowed conclusions.

Label the work:
RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY OBSERVED.

Do not describe these evaluation dates as a pristine holdout.

The plan is fixed before the new diagnostics, not before
all exposure to this dataset.

4. DATASET AND TARGET

Use D7 IBM data and its existing time/price/cost conventions.

Diagnostic-model fitting partition:
D7 LEARNING, 2026-07-06 through 2026-07-17.

Diagnostic evaluation partition:
D7 FROZEN, 2026-07-20 through 2026-07-31.

Reuse the existing frozen probe grid and labels.
Reconcile the reported 2,790 probes against the artifacts;
do not hardcode that count as truth.

For fitting, reconstruct the analogous eligible probe grid
from local data, independent of actual trades and inventory.

Target:
Y(t) = 1 if the existing net fixed-H LONG label G(t) > 0;
       0 otherwise.

Every fitting label must have resolved before evaluation.
Exclude labels crossing the fitting boundary.

Preserve causal feature initialization and bar availability.
Do not derive features from future OHLCV or outcomes.

Prepare two representations:

X_FEATURES:
The exact five feature inputs delivered to the encoder.
Document names, units and existing normalization.

X_SENSORY:
The complete deterministic sensory-rate representation sent
toward the brain, before random spike sampling.

Preserve ordered temporal information if the encoder delivers
a sequence. Do not silently replace a sequence by its mean,
last frame or PC1.

Use fixed channel/time ordering. Do not include:
- ticker/date identifiers as predictive features;
- brain outputs or learned-state hashes;
- account state, rewards or future labels;
- new technical indicators.

Prefer stored inputs. If reconstructing them, verify agreement
against saved encoder outputs where available.

Report finite-value coverage, constant channels, clipping
and exact dimensions for both representations.

5. DESCRIPTIVE FEATURE AND PC1 TABLE

Report per-session raw AUC for each of the five scalar
features, following their existing definitions.

A feature with AUC below 0.5 may rank in the opposite
direction; do not call it automatically uninformative.

For an oriented score, choose its sign from the fitting
partition only, then freeze that sign for all evaluation days.

Never flip signs separately on evaluation days or report
max(AUC, 1-AUC) as held-out performance.

Fit PC1 on centered X_SENSORY from the fitting partition only.
No whitening or evaluation-period PCA fitting.

Record explained variance, loadings and sign convention.
Choose any target-based orientation from fitting data only.

If the representation is constant or PC1 is degenerate,
report that condition rather than manufacturing a score.

This table describes marginal rankings and one projection.
It is not the final input-informativeness verdict.

6. JOINT DIAGNOSTIC MODELS

Use exactly two model families on both representations:
four fitted models total, excluding synthetic unit tests.

LINEAR:
StandardScaler fitted on fitting data only, followed by
L2-regularized logistic regression:
C = 1.0, solver = lbfgs, max_iter = 2000.
No class rebalancing or feature selection.

NONLINEAR:
HistGradientBoostingClassifier:
learning_rate = 0.1
max_iter = 100
max_depth = 3
max_leaf_nodes = 8
min_samples_leaf = 20
l2_regularization = 1.0
early_stopping = False
random_state = 8
No class rebalancing.

Use the repository's compatible dependency versions and
record them. Do not upgrade the production stack unnecessarily.

Do not tune parameters, try additional families, search seeds
or select a model using evaluation performance.

Report convergence/fitting failures without silent replacement.

The primary joint diagnostic is NONLINEAR on X_SENSORY.
The other three are secondary comparisons.

These are external measurement tools with supervised access
to historical labels. They are not biological models and
their results are never attributed to the fly.

Their outputs must have no runtime path to:
the decoder, orders, reward, plasticity or observer decisions.

7. EVALUATION

Use continuous scores and the established D7 session-level
AUC implementation, including tie handling.

Retain D7's minimum class counts and coverage rules.
One-class sessions are undefined, not AUC 0.5.

For each diagnostic report:
- fitting/evaluation row counts and unique sessions;
- class counts;
- per-session AUC;
- equal-session mean AUC;
- coverage and exclusions.

For comparisons between X_FEATURES, X_SENSORY and the fly,
use the same paired evaluation rows and show paired counts.

Reuse the existing whole-session bootstrap:
2,000 draws, fixed registered seed, no fitting inside bootstrap.

Report uncertainty as descriptive and conditional on this
dataset and model fit. Minute probes with overlapping
90-minute labels are not independent examples.

Show all diagnostics. Do not declare a discovery by selecting
the best column or the one interval that excludes 0.5.

Secondary intervals are not simultaneous family-wise evidence.

A result on these reused dates is a lead, not independent
proof of trading ability or a theoretical learning ceiling.

8. TARGET-ALIGNMENT AUDIT

Using only the existing actual LEARNING episodes:

For each entry, report:
- entry time and information cutoff;
- actual exit time and reason;
- actual holding duration;
- gross and net actual outcome;
- actual reinforcement sign;
- hypothetical net outcome at H=90, when available;
- hypothetical fixed-H label.

Summarize:
- how many exits occurred before H;
- actual versus fixed-H outcome signs;
- proportion of sign disagreements;
- counts and magnitude of costs;
- hypothetical-label availability.

Do not use this table to update weights, replay rewards,
modify the account or rewrite the original events.

These counterfactuals reuse the original entry times.
They do not simulate the trades a fixed-hold policy would
actually have taken, because that policy changes inventory
and later entry opportunities.

Do not book the hypothetical outcomes as portfolio PnL.

This audit measures alignment, not whether fixed-hold training
would succeed. A future fixed-hold wave requires a separate
explicit policy amendment.

9. TESTS

Add focused tests for:
- no evaluation rows used in scaler/PCA/model fitting;
- no fitting labels resolving after evaluation begins;
- feature reconstruction with causal timestamps;
- changing evaluation labels cannot change fitted models
  or already-generated scores;
- sign selection uses fitting data only;
- constant scores, reversed rankings, ties and one-class AUC;
- evaluator imports cannot execute orders or apply learning;
- immutable checkpoint and source-log hashes;
- counterfactual outcomes cannot affect bankroll.

Include a deterministic XOR fixture:
each input individually has AUC 0.5, while a joint oracle
score has AUC 1.0.

Its purpose is to prevent the reporting layer from asserting
that marginal chance performance proves absent information.
Do not require every diagnostic model to solve every
possible interaction.

10. CONCLUSIONS AND STOP

Report separately:

INPUT DIAGNOSTICS:
What these limited tests detected or failed to detect,
before and after encoding.

TARGET ALIGNMENT:
How actual reinforcement outcomes differ from the
fixed-horizon quantity used in D7 evaluation.

NEXT-STEP RECOMMENDATION:
A bounded recommendation, not automatic authorization.

Interpretation examples:

- Detectable ranking from X_SENSORY but not from the fly:
  supports investigating learning/readout/target alignment;
  does not prove which component caused the difference.

- Ranking from X_FEATURES but not X_SENSORY:
  motivates inspecting encoding or diagnostic model mismatch;
  does not by itself prove irreversible information loss.

- No stable ranking detected:
  report "no detectable signal with these methods on these
  periods", not "nothing can learn from these inputs".

A negative D8 result does not logically prohibit fixed-hold
experiments. A positive result does not guarantee they work.

Do not launch option (c) automatically.

Deliver the analysis plan, provenance, feature/PC1 table,
four joint-model results, target-alignment table, tests,
exact commands, commits and updated HANDOFF.

Keep downloaded and derived market data outside Git.

Run the existing regression gate twice at closure.
Stop after this single evaluator-only wave.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* D8 = (b) with a correction: the diagnostic may not conclude "there was
  nothing to learn" because each isolated feature and the first principal
  component sit at chance. Two statements of the (f) review do not hold.
  An untrained circuit near AUC 0.5 does not measure the maximum anyone
  could extract from its inputs; it may receive useful information and not
  know how to use it. Univariate and PC1 chance do not exclude joint
  structure: with two binary signals and an outcome positive only when they
  differ, each signal alone is uninformative and the pair is perfectly
  informative — this does not show our data has that structure, it shows
  the proposed test could not rule it out. PC1 seeks the direction of
  largest variance, not the direction that predicts profit. The correct
  diagnostic looks at the inputs alone and jointly.
* D7 taught one task and evaluated another: all 42 operations ended by SELL
  between 1 and 19 minutes, so the 90-minute horizon never determined the
  outcome used to teach the fly, while the discrimination metric asked about
  holding for 90 minutes. The owner's D7 permitted this by preserving the
  early SELL; that choice left a misalignment now acknowledged. It does not
  invalidate the recorded results, it limits their interpretation. Option
  (c), fixed exit during training, can correct it; its justification is
  aligning the taught experience with the evaluated question, not a good
  univariate AUC, and alignment alone does not guarantee learning.
* No further neural run now. The diagnostic uses two external tools, a
  simple linear model and a small nonlinear one, receiving the features
  jointly; neither enters the brain, chooses trades or replaces the fly.
  Fitted on the earlier period, evaluated on the later one; normalisation,
  PCA and every sign choice fitted on the training part only; the split
  respects temporal order and label resolution. Because D7 results on
  these dates were already seen, D8 is an additional retrospective
  analysis, not an independent confirmation on untouched data; fixing the
  plan before the new computations limits opportunistic choices but does
  not erase prior knowledge of the results.
* The owner reviewed the pasted report, not the 379 tests or the repository
  files. Product stance unchanged: the interface and the spectacle are not
  hostage to a proof of profitability; this last diagnostic must
  distinguish "we detected no signal" from "we proved no signal exists",
  and must record that the fly was rewarded on a different duration from
  the one used to evaluate it.

### Fable addenda (reviewer, 2026-09-11) — binding for the D8 wave

0. **Correction to the (f) review, recorded.** Reading (2) of that review
   inferred from REFERENCE AUC 0.4934 that the input might carry no ranking
   information, and D8 option (b) as first offered would have read
   univariate and PC1 chance as an input ceiling. Both inferences are
   withdrawn as the owner states. Amendment §2 is the binding wording and is
   reproduced verbatim at the head of the conclusions in `results.md`.
1. **Facts verified in the tree, which fix the schemas.** Every `DECISION`
   event already stores both representations (`flytrade/records.py:511-517`):
   `observation.normalized` is the five causal features `r1, r5, r20, rv20,
   relvol` z-scored over a trailing 60-bar window (`flytrade/market.py:69-72`)
   and is exactly what `MarketToSensoryEncoder.encode` receives; `stimulus.
   rates_hz` is the deterministic per-glomerulus drive, ten glomeruli, two
   per feature (`flytrade/encoder.py:160-171`), computed before Bernoulli
   spike sampling, one vector per presentation, constant over the 20 ms
   window. The encoder delivers no sequence: the amendment's sequence clause
   is satisfied vacuously and `results.md` says so. X_FEATURES is
   5-dimensional, X_SENSORY 10-dimensional; the eight replicates of a batch
   share one stimulus, so one row per (session, minute), never eight.
   `n_orns` and `total_drive_hz` are provenance, not features.
2. **Stored inputs are primary; reconstruction is the verification.** Rows
   come from the `d7-001` logs: `learned/` for fitting, `frozen_reference/`
   for evaluation (the stimulus does not depend on the branch; assert that
   `frozen_trained/` carries the identical stimulus on every shared row and
   report the count). Then reconstruct both representations from the price
   file with the existing `market`/`encoder` code, seeing only bars with
   `bar_end ≤ market_ts`, and assert agreement within 1e-12 on every row of
   both grids. The mismatch count is a reported number; a non-zero count
   stops the wave before any model is fitted. This is also the causality
   test of §9.
3. **Grids.** Evaluation grid = `withheld-probe-table` rows as they are (count
   reconciled in the plan; 2,790 expected), joined to the FROZEN stimulus by
   (session, minute); `Y` as stored, and the plan records the definition of
   `G` (net, long, H = 90, delay 1, the fill convention of `horizon.hold`).
   Fitting grid = the rule of `experiments/d7/PROTOCOL.md` §6 applied to the
   ten LEARNING sessions 07-06..07-17: a minute whose observation status is
   `OK` and whose H = 90 label is available, labels computed by
   `horizon.hold` from the price file, independent of positions, trades and
   inventory. Labels are session-bounded, so no fitting label can resolve
   after 07-17 16:00; the test asserts `max(exit_ts) of fitting <
   min(market_ts) of evaluation` from the data, not from that argument. The
   −22 % overnight discontinuity 07-13→07-14 lies inside the fitting
   partition: no row spans it, `results.md` names it, and the plan states
   whether any of the five features is price-level dependent (none should
   be).
4. **Session rules.** The ≥ 10-per-class rule and the undefined one-class
   AUC of `flytrade/metrics.py` apply to evaluation sessions; if 07-22 drops
   as in D7 the drop is reported. Fitting uses all resolved rows of all ten
   LEARNING sessions; their per-session class counts are reported for
   information. No matched-participation table for the diagnostics: it is a
   trading-style readout that §2 and §10 would then have to disclaim, and
   AUC already answers the ranking question. `matched_participation` is not
   called by D8.
5. **`flytrade/` is not modified.** Not `metrics.py`, `horizon.py`,
   `market.py` nor `encoder.py`. D8 code lives in `experiments/d8/` and
   `tests/d8/` and imports the existing functions; any helper it needs (an
   unpaired session bootstrap for one diagnostic's mean AUC, for instance)
   is written in `experiments/d8/` and unit-tested on a fixture against
   `roc_auc` and `paired_session_bootstrap`. At the close, re-running
   `experiments/d7/evaluate.py` must reproduce `withheld-probe-table` and
   `context_summary.json` byte-identically: that is the guard that nothing
   under D7 moved.
6. **Bootstrap, defined.** Two uses, both with a seed from
   `metrics.declared_seed` on a label recorded in `config.json`: (a) for
   each of the four models, each oriented feature and PC1, 2,000
   whole-session draws of the qualifying evaluation sessions, mean AUC per
   draw, 2.5–97.5 % interval; (b) paired deltas on identical rows and
   sessions, each diagnostic minus the REFERENCE fly and minus the TRAINED
   fly, through the existing `paired_session_bootstrap` with the diagnostic
   in the first slot. Descriptive, conditional, not simultaneous. The
   primary diagnostic (NONLINEAR on X_SENSORY) is named primary in the plan
   before any number exists; every other line is secondary whatever it
   shows.
7. **Dependency.** scikit-learn is not installed. Add it as a new optional
   extra `diagnostics = ["scikit-learn==<version>"]` in `pyproject.toml`,
   pinned to the newest release that installs against the frozen
   `numpy==2.4.2` / `scipy==1.17.1` on Python 3.13.9 without changing them;
   install it into `.venv`; record the resolved version in `PLAN.md` and
   `results.md`. Main `dependencies` untouched. The D8 tests import sklearn
   directly, no `importorskip`: the gate fails loudly, never skips, if the
   extra is missing.
8. **Determinism.** Run the four fits with `OMP_NUM_THREADS=1`
   (HistGradientBoosting reduces histograms across threads), record it, and
   add a test that two consecutive fits of each family on the fixture
   produce identical scores. Logistic: report `n_iter_` and assert no
   `ConvergenceWarning`; if it does not converge, report that and do not
   raise `max_iter`.
9. **Orientation rule, one place.** For each scalar feature and for PC1:
   raw AUC on the fitting rows; sign = +1 if that AUC ≥ 0.5, else −1;
   written to `experiments/d8/orientation.json` before any evaluation AUC
   is computed, and its hash appears in `results.md`. Evaluation reports
   the raw and the oriented AUC per session; never `max(AUC, 1 − AUC)`.
   PCA by numpy SVD on the fitting-centred X_SENSORY, no whitening;
   explained-variance ratio and the ten loadings recorded; a rank-deficient
   or constant representation makes the PC1 line read "degenerate", not a
   number.
10. **Isolation guards, tested.** `tests/d8/` asserts that no module under
    `experiments/d8/` imports `flytrade.execution`, `flytrade.runner`,
    `flytrade.mushroom`, `flytrade.state` or `flytrade.readout`, and that
    `observer/serve.py` contains no path under `experiments/d8` (the
    observer discovers runs by fixed paths, `observer/serve.py:56-64`;
    nothing there changes). The three `d7-001` event logs and checkpoints
    are sha256-hashed before and after the wave; the hashes appear in
    `results.md`. The alignment audit reads the LEARNING log through
    `flytrade.records` parsing only and writes nothing under
    `experiments/d7/`.
11. **Alignment audit mechanics.** The 42 episodes are the LEARNING log's
    ROUND→DECISION→EXECUTION→OUTCOME→LEARNING chains. For each, the
    hypothetical H = 90 quantity is `horizon.hold` at the original decision
    minute with the original cost constants; assert that its entry fill
    equals the actual entry fill price on every episode and report the
    count. Columns and summary lines exactly as §8 lists, plus min/median/
    max of actual holding minutes and the sign-disagreement count split by
    actual sign. JSON + markdown under `experiments/d8/`.
12. **Cost, order, delivery.** One Opus agent, sequential; compute is
    minutes, no neural run, no download. Commit order, one commit per
    section: (i) `experiments/d8/PLAN.md` + `config.json` ALONE — hashes of
    `withheld-probe-table`, `registered-horizon-artifact`, the price file, the three `d7-001` logs
    and checkpoints; both grid rules; schemas; preprocessing; the model
    parameters of §6; seeds; metric and coverage rules; the allowed
    conclusions; the label RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY
    OBSERVED; the resolved sklearn version — before any D8 number exists;
    (ii) the `pyproject.toml` extra; (iii) grids + stored-vs-reconstructed
    verification; (iv) `orientation.json` + feature/PC1 table; (v) the four
    joint models; (vi) the alignment audit; (vii) `results.md` + `report.py`;
    (viii) HANDOFF block ≤ 25 lines with ENGINEERING, INPUT DIAGNOSTICS,
    TARGET ALIGNMENT and NEXT-STEP RECOMMENDATION apart, the recommendation
    bounded and option (c) not launched. Tests accompany the section they
    test. `pytest tests/` twice only at close, plus addendum 5's byte-identity
    check and `git diff --stat cc9faaf -- upstream tests/upstream_audit`
    empty. Nothing reopened: graph, plasticity fix, gain, window, MBON
    groups, θ, baseline, encoder, decoder, k, H = 90, costs, sizing,
    early-SELL semantics, datasets, run identities.

## D9(a) — viewer product surface — canonical amendment (owner, 2026-09-11, original in English)

D9(a) APPROVED — VIEWER PRODUCT SURFACE

Build one bounded viewer/product wave.
Do not run the fixed-hold experiment in this session.

Read:
- the session log;
- docs/SPEC.md;
- the existing observer implementation;
- canonical event schemas and accepted run artifacts;
- D7 and D8 closing reports.

The reported starting point is f054e75.
Verify the actual full commit and working-tree state locally.

The operational queue lives in the session log.
Do not search for, require or create docs/design/ROADMAP.md.

Append this specification to docs/SPEC.md following the
existing workflow. Keep implementation and review commits
small and explicit.

OBJECTIVE

Turn the existing experiment into a compelling, understandable,
read-only experience that someone can actually watch.

This is an experiment viewer, not:
- a marketing landing page;
- a generic financial dashboard;
- a new trading engine;
- another scientific calibration wave.

The viewer must make this chain understandable:

MARKET CONTEXT
→ ENCODED SENSORY INPUT
→ MEASURED NEURAL RESPONSE
→ DECISION
→ PAPER EXECUTION
→ OUTCOME
→ LEARNING EVENT, WHEN LEARNING IS ENABLED.

No claim of profitable learning is required or authorized.

1. HARD SCOPE

Preserve the scientific and execution core.

Do not change:
- encoder or sensory mapping;
- k, gain, neural window, baseline or thresholds;
- decoder;
- learning or forgetting rules;
- episode-credit assignment;
- position sizing, costs or execution delay;
- early SELL behavior or H=90;
- accepted checkpoints, logs or historical results.

Do not start a new market-neural run for this wave.

Use existing accepted run artifacts for development and
demonstration. Synthetic fixtures may be used for UI tests,
but must never masquerade as historical experiment results.

No:
- fixed-hold policy amendment;
- live market provider;
- real-money execution;
- launch integration or token;
- wallets, distributions or staking;
- accounts, chat or social automation;
- public deployment.

Keep upstream and its audit unchanged.

2. ONE PRIMARY WATCH SCREEN

Design one coherent watch screen, not a wall of equally
important charts.

The primary hierarchy is:

A. MODE AND TIME

Always show:
- source: HISTORICAL REPLAY or SYNTHETIC FIXTURE;
- execution: PAPER;
- phase: LEARNING or FROZEN;
- historical market timestamp;
- playback state and speed;
- selected run/branch identity.

Do not label historical playback LIVE.
Do not confuse playback with a currently running neural worker.

B. CONTEXT AND SENSES

Show the current instrument, the recent market context
available at that point, and the corresponding sensory input.

Use the encoder's actual recorded channels and units.

A user should be able to inspect:
"this measured feature produced this sensory-rate pattern."

Do not invent new features or a visual sensory pathway.
The current market encoder uses the declared olfactory path.

C. THE FLY AND NEURAL RESPONSE

Make the fly/circuit the visual focus.

Show measured population activity, aggregate response and
the decoder output.

D. DECISION AND POSITION

Show the current decision, execution status, open paper
position and any applicable policy limit.

E. RESULT AND MEMORY

When an episode settles, show its actual result and, only
when present, the associated learning update.

Keep secondary scientific detail available on demand,
rather than putting all audit metrics in the main view.

3. VISUAL DIRECTION

Use a deliberate, polished observation-chamber aesthetic:
dark neutral background, clear typography, restrained color,
large readable numbers and purposeful motion.

The fly is the protagonist; financial charts are supporting
information.

Avoid:
- a generic grid of neon cards;
- a giant decorative brain graph with meaningless activity;
- floating random numbers;
- a landing-page hero that hides the experiment;
- theatrical personality claims unsupported by the record.

Use existing licensed assets when suitable and retain notices.
Otherwise use a lightweight schematic mascot/circuit treatment.

Do not introduce a heavy 3D engine or a framework migration
just to obtain a visual effect.

A mascot animation is presentation, not a measured motor
command. Keep that distinction clear.

Neural visualization must represent available telemetry:
- population rates may drive population intensity;
- actual recorded spikes may drive spike marks;
- actual recorded learning deltas may drive change highlights.

Do not turn aggregate firing rates into invented individual
spike trains or claim exact anatomical coordinates that are
not available.

Schematic diagrams are allowed and must be identifiable as
schematics.

Support desktop and narrow mobile layouts.
Keep text, contrast and controls readable.
Provide reduced-motion and sound-off defaults.

4. HONEST STATE AND EVENT SEMANTICS

Use canonical backend events and statuses.

Keep distinct:
- valid BUY / SELL / WAIT signals;
- NO_RESPONSE;
- INVALID or saturated neural state;
- execution-policy rejection;
- order/fill;
- neural SELL closure;
- POLICY_CLOSE or session closure;
- outcome;
- learning application.

A SELL signal without a position is not an executed sale.

A policy closure is not a neural decision.

H=90 is the existing policy horizon, not a promise that a
trade will remain open for 90 minutes. If displaying a timer,
label it as the remaining maximum policy horizon.

Do not animate reward, punishment or changed weights during
FROZEN when those events did not occur.

A positive frozen outcome may be displayed as:
"Positive result — learning frozen."

In LEARNING, a positive outcome is not enough to claim that
weights changed. Use the actual learning event and delta.

If an outcome is neutral, no update occurred, or eligible
synapses were absent, show that actual condition.

Show k=8 as the measurement policy.

Only show per-replicate progress or timings when recorded.
If the log contains only a completed aggregate, present it
as a completed measurement.

Do not fabricate a real-time "thinking" process from events
that were never recorded.

5. RESULTS, ACCOUNTING AND HISTORICAL FRONTIER

All financial values come from canonical recorded state or
the existing verified read-only event projection.

Do not implement a second PnL engine in browser JavaScript.

Distinguish:
- paper cash;
- inventory/exposure;
- marked equity, when available;
- unrealized result, when available;
- gross realized PnL;
- costs;
- net realized PnL.

Show units and sign consistently.

If a field was not recorded and cannot be reconstructed
through an existing verified projection, show unavailable.
Do not invent starting balances or derive approximate values
without labeling them.

At playback time T, reveal only events and values available
through the current event frontier.

Do not display:
- final-run PnL during an earlier decision;
- a later trade outcome beside its entry;
- future reward-colored timeline markers;
- final lifetime statistics as if already accumulated.

Use event sequence as well as timestamps when multiple
events share the same timestamp.

Final experiment summaries belong at completion or behind an
explicit "show final report" action, separate from watch mode.

6. PLAYBACK THAT REMAINS INTERESTING WITHOUT FAKE ACTIVITY

Provide:
- play/pause;
- a small set of playback speeds;
- seek;
- next decision;
- next executed trade;
- next learning event;
- return to the start.

Playback controls affect presentation only.

They must not alter:
market time, brain time, seeds, decisions, execution,
reinforcement, learned weights or canonical logs.

If the user skips an uneventful interval, indicate that an
interval was skipped. Do not imply continuous action.

Seeking backward and replaying must reconstruct the same
as-of state without double-counting trades or learning.

Offer the latest accepted LEARNING trace as the default
watch experience, identified from the actual repository.

Also expose FROZEN and its reference branch when artifacts
exist. Do not default to a run because it has better PnL.

Long inactivity, repeated losses and suppression remain part
of the record.

Completed, paused, loading, disconnected and missing-data
states must be distinct. A completed replay is not an outage.

7. DETAIL PANEL AND SCIENTIFIC RECORD

Provide an expandable decision/episode detail panel with:
- run, decision and episode IDs;
- historical observation cutoff;
- instrument and recorded feature values;
- sensory input;
- relevant population readouts;
- aggregate decoder score and threshold;
- action and execution-policy result;
- linked fill/outcome/learning events;
- checkpoint/version references.

Large arrays belong behind a detail control, not in the
primary watch screen.

Add a compact experiment-record view using accepted results.

The scientific summary must remain:

D7:
Suppression without demonstrated improvement in the
fixed-horizon context-discrimination metric.

D8:
No detectable signal with the specified diagnostic methods
on the tested periods.

Training/evaluation target mismatch:
Early-exit outcomes were used for reinforcement while the
D7 probe target used a 90-minute hold.

Do not turn these into:
- proof that no learner can use the inputs;
- proof of learned profitable trading;
- proof that the target mismatch has already been corrected.

Do not assume the 36.6% positive probe base rate predicts the
reward rate of a future selected, inventory-constrained
fixed-hold policy.

Use exact artifact-backed values, not rounded numbers copied
from chat when the underlying results are available.

Keep fixed-hold as a pending separate experiment in HANDOFF.

8. TECHNICAL IMPLEMENTATION

Extend the existing local observer and event pipeline.

Prefer the current stack or lightweight HTML/CSS/JavaScript.
Do not rewrite the repository around a new application stack.

A small read-only adapter/presentation layer is allowed.

It must:
- read canonical accepted artifacts;
- expose stable run/event identities;
- preserve event order;
- handle missing optional telemetry explicitly;
- avoid modifying logs or checkpoints.

Do not import a worker startup path that can trigger trading
or learning just to render the viewer.

Keep expensive data processing off the browser render loop.

Bind locally by default on the existing observer port where
compatible. Serve only viewer assets and approved read-only
run projections, not the repository root.

No public ingress, arbitrary filesystem-path endpoint,
credentials endpoint or unrestricted RPC passthrough.

Do not expose .env, raw downloaded market files or checkpoint
binaries as ordinary public static assets.

Define a small presentation-event contract so another data
source can be connected later, but do not implement that
future live integration now.

9. TESTS AND VISUAL VERIFICATION

Add focused tests for:
- canonical-event → displayed-state mapping;
- no future outcome leakage during playback;
- same-timestamp event ordering;
- backward seek and deterministic replay;
- no duplicate financial/learning counts after reconnect;
- WAIT versus NO_RESPONSE;
- signal versus executed trade;
- neural closure versus policy closure;
- FROZEN outcomes without invented learning;
- missing optional telemetry;
- playback controls without core-state mutation;
- local server exposure boundaries.

Test recorded loss episodes as well as positive ones.
Use explicitly marked fixtures for states absent from the
selected historical run.

Open the actual page in an available browser/test runner.
Do not consider source-code inspection sufficient visual QA.

Verify desktop and narrow mobile layouts.
Capture the rendered key states:
- sensory observation / neural response;
- decision and open position;
- settled result and actual learning event;
- frozen result without learning;
- inactivity or no-response state.

Use screenshots or a short local capture as evidence.
Do not report browser verification that was not performed.

10. COMPLETION GATE AND HANDOFF

The gate is not "more tests passed."

A reviewer must be able to start the viewer, select an
accepted run and follow a real recorded episode from market
context through outcome and learning without reading JSON.

The interface must remain truthful when the fly does nothing,
loses, or is evaluated with frozen weights.

Deliver:
- working viewer;
- exact local startup command and URL;
- default accepted run and artifact provenance;
- screenshots or captured browser evidence;
- read-only adapter/event-contract documentation;
- focused tests and full regression results;
- commits and clean-tree state;
- updated HANDOFF with the queue kept in that file.

Preserve the reported existing regression baseline and
strict upstream xfails. Add tests; do not weaken old ones.

Run the full regression gate twice at closure according to
the established workflow. Do not run another market-neural
experiment as part of this product wave.

Report separately:
A. Viewer functionality.
B. Visual verification.
C. Telemetry/accounting fidelity.
D. Known missing data or presentation limitations.

Stop after D9(a).

Do not also implement D9(b), change the science, or prepare
a launch in this session.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* D9 = (a): product now. The owner would not open another neural wave
  before there is a genuinely good experience of watching.
* On the (g) closing as reported: D8 did its job — it detected no signal
  with those methods and periods, and it confirmed the mismatch between the
  outcome used to teach and the outcome used to evaluate. It did not prove
  the fly can never learn; it also gave no strong reason to keep changing
  the experiment before showing what already exists.
* The owner decides on the report as presented, and does not assert having
  personally verified the commit or the 481 tests.
* Correction before advancing: the 36.6 % positive results of the grid do
  not mean that a fly operating with a fixed exit would receive 37 %
  rewards. It would choose certain entries, and holding a position for
  90 minutes would change which subsequent entries were available. That
  rate describes the grid, not the result of a policy not yet executed.
* Fixed exit remains a defensible experiment to align training and
  evaluation. It is recorded as a pending item, not as a prerequisite of
  this wave and not as a correction already made.
* What to build: not a landing page with a profit chart, but the screen
  where you follow the fly. You open it and understand: "this is what she
  received; this is what the brain answered; this was the decision; this
  happened afterwards; these connections changed." At the centre, the fly
  and a visual representation of the circuit. On one side, the market
  context being translated into stimuli. On the other, the response and
  the position. When an operation closes, the result appears next to the
  corresponding learning event.
* Two essential differences: in FROZEN no learning is shown happening,
  because the weights are frozen; and a SELL signal is not shown as an
  executed sale when there was no position. These details make the
  experience represent the real system.
* No invented trades to fill the periods when she stays out. Allow
  advancing to the next recorded decision, operation or learning update,
  keeping the chronology.
* The next delivery has to be something you open and watch — not another
  table to interpret in order to imagine the product. The experiment stays
  preserved; now give shape to what it actually does.

### Fable addenda (reviewer, 2026-09-11) — binding for the D9(a) wave

0. **Correction to the (g) review, recorded.** That review's "the reward
   would run ≈ 37/63 instead of 5/37" is withdrawn as the owner states: the
   36.6 % LEARNING-grid base rate describes probes on a grid, not the reward
   rate of a selected, inventory-constrained fixed-hold policy that has not
   been executed. The viewer's experiment-record view (§7) must not carry
   any such projection. Fixed-hold stays in HANDOFF as a pending separate
   experiment, neither prerequisite nor done.
1. **Facts verified in the tree, which fix the starting point.**
   `observer/serve.py` is standard-library `http.server`, `HOST` fixed to
   `127.0.0.1` (`serve.py:80`), default port 8765, serving `index.html` and
   four read-only endpoints: `/api/runs`, `/api/summary?run=`,
   `/api/events?run=&branch=&partition=`, `/api/artifact?run=&name=`
   (`horizon`, `context`, `probes`, `learning`). `observer/index.html`
   already has run/branch/partition selectors, play/step/speed controls and
   the sections Clock, Instrument being presented, Encoded sensory channels,
   Measured neural readout. D9(a) **extends this page and this server**; it
   does not start a second server, a second page hierarchy or a build step.
   The canonical event kinds are exactly the ten of `EventType`
   (`flytrade/records.py:68-88`): `ROUND`, `ROUND_ABORTED`, `DECISION`,
   `EXECUTION`, `OUTCOME`, `LEARNING`, `CHECKPOINT`, `RECOVERY`, `WARMUP`,
   `PARTITION`. No displayed state may derive from anything but these
   events, the run's `summary.json` and the four committed artifacts.
   Runs on disk: `hist-001..003` (D5/D6) and `d7-001` with branches
   `learned`, `frozen_trained`, `frozen_reference`, each holding
   `events.jsonl` (≈ 13 MB; `learned` has 7,786 lines: 3,899 ROUND, 3,699
   DECISION, 42 EXECUTION, 42 OUTCOME, 42 LEARNING, 44 CHECKPOINT,
   13 WARMUP, 4 PARTITION, 1 RECOVERY) and `brain.npz` (mode 600). Both
   run directories are **gitignored**: the viewer must work with them
   present and show a distinct missing-data state when absent, and the
   tests must pass in both conditions.
2. **Default and selection.** `d7-001/learned` is the latest accepted
   LEARNING trace and is the default; `frozen_trained` and
   `frozen_reference` are exposed as branches of the same run;
   `hist-001..003` stay reachable through the existing run list without a
   redesign for them. Selection is by identity, never by result. The
   3,899 ROUND against 3,699 DECISION and 42 EXECUTION of the default trace
   are the record: the screen is designed for a fly that mostly waits, is
   sometimes unreadable, and traded 42 times in ten sessions.
3. **Domain semantics live in Python and are tested by pytest; the browser
   merges frames and renders.** A new read-only module (e.g.
   `observer/projection.py`) turns the canonical event list into an
   ordered presentation stream keyed by `(seq, ts)` where `seq` is the
   line index in `events.jsonl` — the tie-break for equal timestamps §5
   asks for — with the small payload the screen needs, and produces the
   as-of state after each event (keyframes plus deltas, or equivalent) so
   that (a) the state at cursor N is a pure function of events 0..N and the
   no-leakage property is a Python test; (b) backward seek is an index, not
   a re-fold in JavaScript, so double counting is structurally impossible;
   (c) every distinction of §4 — WAIT vs NO_RESPONSE vs INVALID/saturated,
   signal vs executed trade, NEURAL_SELL closure vs POLICY_CLOSE, FROZEN
   outcome without learning, missing telemetry, execution-policy rejection
   — is a named branch in Python with a pytest case on a loss episode and
   on a positive one. The JavaScript folds nothing beyond merging
   server-produced frames. Node v20 exists on the machine but is **not**
   part of the gate; no JavaScript test harness is added.
4. **Isolation is mechanical.** Neither `observer/serve.py` nor the
   projection module imports anything from `flytrade` (D8 risk 6:
   `flytrade.records` pulls in `runner`/`state` transitively). The event
   kind strings are duplicated as constants in the projection module, and
   one test — which may import `flytrade.records.EventType` — asserts the
   two sets are equal. This satisfies §8's "do not import a worker startup
   path" by construction, and a test asserts `sys.modules` contains no
   `flytrade.*` after importing the observer modules.
5. **Payload budget.** The presentation stream for `d7-001/learned` is
   ≤ 5 MB and loads in under 2 s locally, measured and reported; heavy
   fields (`replicate_scores`, full `stimulus.rates_hz`, `observation.raw`,
   arrays in LEARNING) go behind `/api/detail?run=&branch=&seq=`, one
   canonical event returned unchanged, on demand. The existing
   `/api/events` stays exactly as it is (D6 tests cover it).
6. **Exposure boundary, tested.** The server serves only `index.html`,
   files under an explicit allowlist in `observer/static/` matched by exact
   name (no traversal), and the read-only JSON endpoints. Tests assert
   404 (or 403) for `/../`, `/.env`, `/pyproject.toml`, `/data/…`,
   `/experiments/d7/runs/d7-001/learned/brain.npz`, any path ending in
   `.npz`, `.feather` or `.jsonl`, and that `HOST` is still `127.0.0.1`.
   No endpoint accepts a filesystem path; runs and branches are looked up
   by id against the discovered set and unknown ids return 404.
7. **Offline.** The page makes no external network request: no CDN, no
   web font, no analytics. A test greps `index.html` and `observer/static/`
   for `http://` and `https://` in `src=`, `href=`, `@import` and `url(`
   and fails on any hit other than the local origin.
8. **Neural figure and replicates: recorded, not timed.** `DECISION`
   already stores `replicate_scores`, `replicate_statuses` (k = 8),
   `silent_replicates`, `readout_status`, `readout.kc_active`,
   `readout.kc_fraction`, `readout.rates_hz.approach/avoid`,
   `readout.population_sizes`, `approach_hz`, `avoid_hz` and
   `decoded_action`. The viewer may show eight replicate marks with their
   recorded status and score **as a completed measurement**; no
   per-replicate timing exists in the log, so none is animated. The
   circuit figure is driven by `readout.rates_hz`, `kc_active`/`kc_fraction`
   and, on LEARNING events, the recorded delta fields, and carries the word
   SCHEMATIC visibly. Verify every field name in `flytrade/records.py`
   (`record_round`, `record_decision`, `open_episode`, `settle`,
   `settle_frozen`, lines 462-632) before use, and list in the contract
   document which canonical field feeds which visual.
9. **Accounting.** Display only fields actually written by `open_episode`,
   `settle` and `settle_frozen` and whatever the D6 verified projection in
   `summary.json` carries; "unavailable" for the rest, never 0 or a guess.
   `settle_frozen` writes `settlement: "SETTLED_FROZEN"` and a learning
   record `{accepted: False, reason: "frozen evaluation: learning is
   off"}`: that is the source of "result — learning frozen", not the
   branch name. `summary.json` keys (`graph_sha256`, `encoder`, `decoder`,
   `readout_learning`, `readout_frozen`, `branches`, `config`) are
   run-level provenance for the identity strip and the record view, never
   as-of values. Every financial value in the detail panel is labelled
   with the canonical field it comes from.
10. **Assets.** `upstream/assets/flycoin*.png` are token imagery and are
    out: the launch layer never enters Flytrade code or docs.
    `upstream/site/web/fly.png` may be used only if on inspection it
    carries no coin or token branding, with the MIT notice from
    `upstream/LICENSE` reproduced in `observer/static/NOTICE`; otherwise a
    schematic SVG authored in this wave. Any raster added is ≤ 200 KB.
11. **Browser verification.** Use the headless Chromium already on the
    machine (`/snap/bin/chromium`, or a Playwright Chromium build under
    `~/.cache/ms-playwright`, **without** adding the `playwright` package
    to the venv) or the chrome-devtools tools if reachable. Viewports
    1440×900 and 390×844 — one mobile breakpoint, not a matrix. Save PNGs
    under `observer/evidence/d9a/` (≤ 300 KB each, committed) for the five
    states of §9 plus the run selector, and say in the report which tool
    captured them. If no browser works, say so and do not claim visual QA.
    The reviewer will not open the images; the report describes them.
12. **Tests and gate.** New tests under `tests/observer/`; fixtures carry
    `"dataset_label": "SYNTHETIC_FIXTURE"` in every event so nothing
    synthetic can pass as historical; the tests pass with the run
    directories absent, and at most one test asserts on `d7-001/learned`
    real counts, skipped with a reason when absent. Full gate
    `.venv/bin/python -m pytest tests/` twice at closure; baseline
    `481 passed, 2 xfailed`; no existing test modified. At closure
    `git diff --stat f054e75 -- flytrade upstream tests/upstream_audit
    experiments/d7 experiments/d8 experiments/historical` is empty.
13. **Commits and report.** Small commits in this order: projection +
    tests; server endpoints + exposure tests; page and visual; evidence +
    contract document; HANDOFF block (≤ 25 lines, queue kept in the file,
    fixed-hold listed as pending). Identity `-c user.name="Claude Fable
    5.1" -c user.email="noreply@anthropic.com"`. The report is text only,
    with §10's A–D, the startup command and URL, the payload measurement,
    the two gate outputs, the commit list and every deviation from this
    spec declared rather than absorbed.
14. **Bounded polish.** One screen, the five states, one dark theme, no
    theme system, no sound, no settings page. If the wave passes ≈ 4 h of
    agent time or the design starts growing panels, stop, commit what
    holds, and report what is missing instead of finishing at any cost.

## D9(b) — target-aligned fixed-hold experiment — canonical amendment (owner, 2026-09-11, original in English)

NEXT BACKEND WAVE — D9(b), TARGET-ALIGNED FIXED-HOLD EXPERIMENT

The visual/presentation work will be handled separately.
Do not spend this wave on styling, static export, hosting
or public deployment.

Read the session log and the accepted D7/D8 artifacts.
The operational queue remains in the session log.

OBJECTIVE

Run the pending experiment in which the quantity used for
reinforcement matches the quantity used for evaluation.

This is an explicit execution-policy amendment, not a claim
that the original early-exit experiment never happened.

Preserve all original runs and conclusions.

1. FIXED COMPONENTS

Use IBM, the existing local dataset and the same D7 partitions.

Reuse the previously selected H=90 calibration artifact.
Do not recalibrate H or search another date window.

Preserve:
- encoder and causal feature processing;
- k=8, gain, neural window and baseline;
- MBON membership, decoder and thresholds;
- sizing, execution delay, fees and slippage;
- normalized learning and episode-credit assignment.

Start from the clean reference checkpoint used for the
original experiment, not from the suppressed trained brain.

This is a retrospective comparison on previously examined
dates. Do not describe it as a new untouched holdout.

2. EXPLICIT FIXED-HOLD POLICY

Apply the fixed-hold policy to both LEARNING and FROZEN
paper execution.

When flat, the existing neural decision determines entry.
Do not force entries to generate training examples.

After an entry fills:
- keep one position open;
- do not increase or reverse it;
- close at the declared H=90 target;
- label the closure POLICY_CLOSE_FIXED_HOLD.

Neural SELL signals observed while holding may remain in
the diagnostic log, but cannot close this version's position.
Record them as signals blocked by the fixed-hold policy,
not as executed sales.

This experiment tests entry-context selection.
It does not test learned exit timing.

Do not modify the decoder to compensate for removing
early exits.

3. ONE TARGET DEFINITION

Inspect the original fixed-H label timing before coding.

Use one shared definition of entry timing, target timing,
fill prices and costs for:
- the actual fixed-hold episode outcome;
- the evaluator's corresponding fixed-H label.

Document whether H starts at entry fill or another existing
anchor. Do not leave actual execution and labels using
different anchors.

Add an invariant:
for the same entry and valid price availability, the actual
net fixed-hold outcome equals the evaluator's corresponding
net label, subject only to documented numeric tolerance.

Keep the original execution delay unchanged.
Do not introduce same-bar hindsight fills.

Prevent ordinary entries whose target would cross the session
or partition boundary.

Handle missing prices and exceptional closures explicitly.
Keep their accounting and logs; do not silently discard them
or pretend they were exact-H outcomes.

4. REINFORCEMENT

One completed episode produces at most one normalized
learning update.

Attribute that update to the entry decision's stored sensory
experience and eligibility traces, not to observations made
later while waiting for the position to close.

Preserve the existing documented delayed-credit convention.

No intermediate-PnL reward.
No counterfactual reward for skipped entries.
No reward from a blocked SELL signal.
No repeated punishment for the same open position.

Keep the net-outcome reward rule and costs unchanged.

5. FROZEN EVALUATION

Compare:
- the newly trained fixed-hold checkpoint;
- the clean untrained reference.

Disable learning and forgetting in both frozen branches.
Verify unchanged learned-state hashes.

Use the existing paired comparison seed policy, independent
of learned-state digest.

Retain the D7 continuous-score context-discrimination metrics,
common probe grid, coverage rules and session-level uncertainty.

Report actual paper trading separately from hypothetical
probe labels.

Compare context ranking, not just the number of BUY actions.

Report:
- actual holding durations and exit reasons;
- reward/punishment counts;
- completed episodes;
- BUY/SELL/WAIT and NO_RESPONSE;
- gross/net results and costs;
- trained/reference AUC and paired differences.

Do not infer the realized reward rate from the 36.6% positive
probe base rate. Selected entries and occupied inventory change
which episodes actually occur.

6. PREREGISTRATION AND TESTS

Commit the policy amendment, configuration, seed schedules
and evaluation plan before the new neural run.

Add tests proving:
- early neural SELL cannot close fixed-hold positions;
- entry remains controlled by the existing neural decoder;
- outcome and evaluation-label timing/costs agree;
- later observations cannot receive the entry's reward;
- session and partition boundaries remain correct;
- crash/restart cannot duplicate a close or learning update;
- frozen weights remain unchanged.

No parameter changes after observing results.
No repeated seeds or periods selected for a favorable outcome.

7. DELIVERY

Deliver one completed, target-aligned experiment with:
- configuration and provenance;
- checkpoint hashes;
- chronological event log;
- target-alignment invariant results;
- actual episode/holding-duration table;
- frozen comparison and context-discrimination metrics;
- regression tests run twice;
- commits, clean-tree status and updated the session log.

Allow the existing observer to open the new run through its
existing contract. Do not redesign the viewer.

If the system produces too few trades or informative evaluation
sessions, report INCONCLUSIVE. Do not manufacture activity.

A negative scientific result does not fail the engineering gate.
A positive result does not establish general trading ability.

Stop after D9(b).
Do not also implement live data, static hosting or real execution.

### Owner rationale recorded with the amendment (2026-09-11, from Portuguese)

* Priority changed against the (h) review's recommendation: the visual and
  presentation work goes to other collaborators; Claude runs the aligned
  test now, and the next wave is not spent exporting a replay.
* Today a historical run works and there is a way to watch it. The fly
  receiving new market continuously does not exist yet.
* First: redo the experiment with training and evaluation on the same task.
  That is D9(b): she chooses to enter, the position stays for the defined
  horizon, and the reinforcement corresponds to that same horizon. Then
  that version is evaluated without further weight changes. It needs no
  hosting, no new provider and no pretty interface; it uses the
  infrastructure and data already in place, and it answers the reviewer's
  own complaint that this test is still owed. Technically it is a new
  experimental policy, because before the fly herself could exit early —
  not merely a correction to a report.
* Second: put the system to work with market arriving now — the provider,
  the continuous process that receives new observations, failure recovery,
  and the observer following new events. The delivery is: an observation
  arrives, the fly responds, the system records the decision and later
  resolves the outcome, without anyone manually starting another run.
* Third: make it available to other people and, later, integrate real
  execution. Publishing a replay is a shareable demonstration; it does not
  replace the continuous process. Correction to the (h) review's wording:
  real money and the launch were deferred in the specifications, not
  eliminated from the idea. The real-order executor remains a future stage,
  separate from the simulation engine.
* States that have not appeared naturally, such as an invalid reading, do
  not need to be provoked in a run to "complete the product". They need to
  be correctly handled and tested.
* On exporting the replay: the Kibot licence limits the data to internal
  use and its definition of data includes related or derived information.
  "Publishing only the projection" is therefore not automatically a
  redistribution authorisation. The replays stay local while the owner
  defines which information may compose the public demonstration.
* Order: finish the aligned test; then switch on current market with paper
  operation and continuous observation. The visual track runs separately.
  Publishing a static file may help show the project, but must not take the
  place of those two deliveries.

### Fable addenda (reviewer, 2026-09-11) — binding for the D9(b) wave

0. **Corrections to the (h) review, recorded.** Its D10 option (a) is not
   the next wave; the static export it suggested is withdrawn under the
   Kibot licence reading above; and "excluded" was the wrong word for
   real-money execution and the launch layer — both are deferred. D9(b) is
   now authorised, exactly as the amendment bounds it.
1. **Facts verified in the tree, which fix the mechanism.** The D7 loop is
   `experiments/historical/run.py::run_branch` (as `experiments/d7/run.py:29`
   states). Positions close at three sites: `run.py:346-349`, `POLICY_CLOSE`
   when holding and `due_for_horizon(m)`; `run.py:398-401`, on a decoded
   SELL — `POLICY_CLOSE` if due, otherwise `NEURAL_SELL`; `run.py:536`,
   `POLICY_CLOSE` at the last bar of a partition. `HistoricalExecutionPolicy`
   (`flytrade/historical.py`) already refuses an entry whose horizon would
   cross the session — `eligible_to_enter`, `(m+1)+1+H ≤ 390`, lines
   790-792, `RejectReason.SESSION_HORIZON` at 814-815 — and locates every
   fill with `flytrade.horizon.locate`, the one primitive the evaluator's
   `Hold` also uses: exit at the first bar at or after **the entry fill
   minute + H** (`historical.py:737`; `Hold.exit_delay`, `horizon.py:128-130`),
   and `Hold.net_return` is documented as computed exactly as
   `ExecutionPolicy._settle`. So the anchor §3 asks about is **the entry
   fill minute**, H = 90 market minutes from it, and the invariant is
   expected to hold **exactly**; a tolerance is allowed only for float
   rounding (≤ 1e-9 on net PnL) and is reported per episode, never assumed.
2. **The amendment is one flag.** Add `exit_policy` to the run
   configuration with values `neural_or_horizon` (D7's behaviour, the
   default) and `fixed_hold`. Under `fixed_hold` the site at
   `run.py:398-401` does not close: the decoded SELL is routed through the
   policy's `reject("SELL", …)` with a new `RejectReason.FIXED_HOLD`, so it
   lands in the DECISION's existing `execution` record as a rejection — the
   schema already carries rejections — and the round tally counts it under
   a new `blocked_by_fixed_hold` key. The horizon close at `run.py:346-349`
   is labelled with a new `CloseReason.POLICY_CLOSE_FIXED_HOLD` under the
   flag; the D7 path keeps `POLICY_CLOSE`. The end-of-partition close at
   `run.py:536`, `END_OF_DATA` and `SESSION_CLOSE_FILL` keep their labels
   and are reported as exceptional closures, counted apart, never as
   exact-H outcomes. `flytrade/execution.py` and `flytrade/historical.py`
   change only by these enum members and the routing; no decoder, gain,
   threshold or learning rule changes. A test runs the shared loop on one
   fixture under both flag values and asserts the default reproduces D7's
   closure sequence event for event; the existing `tests/historical` and
   `tests/d7` tests pass unmodified.
3. **Eligibility after 90 rounds is proven before the run — STOP
   condition.** D7's 42 LEARNING events were all accepted, with
   `eligibility_source: "replayed_from_decision"`, at holds of 1–19 market
   minutes (read from the log); the stored trace set is captured at
   decision time (`flytrade/runner.py:382-393`, `553-554`), and
   `RejectionReason.TRACE_EXPIRED` exists (`runner.py:534-535`). Before the
   plan is committed, the wave establishes from the code whether a stored
   trace replayed after 90 rounds — ≈ 90 brain cycles and 89 intervening
   decisions, including `clear_episode`, `present` and any `decay` call —
   settles identically to one replayed after 1 round, and adds a unit test
   that settles a stored trace after 90 idle rounds with the same
   `synapses_depressed` as after 1. If eligibility is not preserved the
   wave **stops before any run** and reports: changing decay or eligibility
   is a science change the owner has not authorised.
4. **Fixed components, by artifact.** `experiments/d7/config.json` dates,
   partitions and instrument (IBM, sha256 `b1ace385…`); `registered-horizon-artifact` with
   H* = 90 and the sha256 `context_summary.json` records for it; clean
   reference digest `ba95b60503d6…`; graph `8feb08a0d2a8…`; notional, fee,
   slippage, delay 1; the `comparison_v1` paired seeds. New directory
   `experiments/d9b/` with `PLAN.md` + `config.json` committed **alone**
   before any run, listing the sha256 of every reused artifact, the flag
   value, the seed schedules, the evaluation plan, the STOP conditions and
   the allowed conclusions. Every report is labelled RETROSPECTIVE
   COMPARISON ON PREVIOUSLY EXAMINED DATES.
5. **Expected activity, written before the run so it cannot be read as a
   result.** With H = 90 and `eligible_to_enter`, one session admits at most
   three fixed-hold episodes (entries up to minute 298, one position at a
   time), so LEARNING yields at most 30 completed episodes and each FROZEN
   branch at most 30, against D7's 42 / 2 / 260 trades. The plan states the
   INCONCLUSIVE rule numerically before the run — e.g. fewer than 10
   completed LEARNING episodes, or fewer than 5 qualifying evaluation
   sessions under D7's rule — rather than deciding it afterwards.
6. **Reinforcement.** Exactly one `journal.settle` per completed episode,
   valence from the existing net-outcome rule; blocked SELL signals produce
   no reward, no punishment and no trace change; observations while
   holding produce DECISION events as decoded (WAIT / SELL / NO_RESPONSE)
   but never an EXECUTION; a test asserts the LEARNING event's
   `episode_id` equals the entry decision's, and that no LEARNING event
   exists for an episode without an OUTCOME.
7. **Evaluation reuses D7's code without touching it.** The probe grid,
   labels, coverage rule and session AUC are `experiments/d7/evaluate.py`'s;
   a `experiments/d9b/evaluate.py` may import from it but never modifies
   it, and D7's `withheld-probe-table` stays byte-identical. Actual trading and probe
   labels are separate tables; the paired comparison is trained vs
   reference on identical rows and sessions with the D7 bootstrap seeds
   declared in the plan.
8. **Restart safety.** Reuse the existing fault injection (`InjectedFault`:
   `after_outcome_event`, `after_learning_applied`, `after_checkpoint`,
   `after_pending_cleared`) on a fixed-hold fixture; after recovery, one
   OUTCOME and one LEARNING per episode and an equal checkpoint digest.
9. **Observer, minimal.** Add the `experiments/d9b/runs` root to `ROOTS` in
   `observer/serve.py` (the mechanism D7 used); in `observer/projection.py`
   map `POLICY_CLOSE_FIXED_HOLD` to the policy-closure branch and
   `FIXED_HOLD` rejections to "SELL signal · blocked by fixed-hold policy",
   each with a test; the `hist-00x` / `d7-001` projections are byte-identical
   before and after (test on a fixture). No other viewer change.
10. **Compute and time.** D7 took 15.0 min (learn) + 31.3 min (frozen) at
    679 MiB peak; expect ≈ 50 min here, nothing else running concurrently,
    the gate after the run. Agent budget ≈ 2 h beyond compute; past that,
    commit what holds and report what is missing.
11. **Gate.** `.venv/bin/python -m pytest tests/` twice at closure; baseline
    `561 passed, 2 xfailed`; no existing test modified;
    `git diff --stat 3a3ab49 -- upstream tests/upstream_audit experiments/d7
    experiments/d8 experiments/historical/runs data` empty; the exact diff of
    `flytrade/` and of `experiments/historical/run.py` is reproduced in the
    report (`git diff --stat` plus the enum and routing hunks).
12. **Commits, in order.** (1) `experiments/d9b/PLAN.md` + `config.json`
    alone; (2) flag, enum members, routing and their tests; (3) observer
    mapping and tests; (4) run logs, summaries, `results.md` (events and
    checkpoints stay gitignored, as for D7); (5) HANDOFF block ≤ 25 lines,
    queue: live market with paper execution and continuous observation
    next, then sharing, then real execution; replays local under the Kibot
    licence. Identity `-c user.name="Claude Fable 5.1" -c
    user.email="noreply@anthropic.com"`. Report text only: the invariant
    table, the episode / holding-duration table, the frozen comparison,
    the two gate lines, the diff, every deviation declared.
13. **Wording.** A negative result reads "no improvement detected under the
    fixed-hold policy on these periods"; a positive one is not general
    trading ability; the 36.6 % base rate predicts nothing; D7's conclusion
    B and D8's conclusions stand unrewritten. Never "the fly learned".

## D10 — Pons memecoin environment — canonical amendment (owner, 2026-09-12, original in English)

CANONICAL PIVOT — PONS MEMECOIN ENVIRONMENT
IMPLEMENTATION + EXISTING-STACK REUSE

You are implementing the next backend wave of the existing
fruit-fly trading experiment.

This is an explicit product-direction amendment.

The target environment is now:
MEMECOINS LAUNCHED THROUGH PONS ON ROBINHOOD CHAIN.

Do not continue the proposed Alpaca/IBM live integration.
Do not repeat the completed scientific experiments.
Do not rebuild the brain from scratch.

Read the session log and docs/SPEC.md first.
Verify the actual current commit, working tree and accepted
implementation. The queue lives in the session log.

Preserve completed IBM experiments as historical evidence.
They are not the product's future market universe.

Append this amendment using the established workflow.
Mark conflicting pending Alpaca/IBM instructions SUPERSEDED,
without deleting their history.

State your bounded implementation plan, then implement it
in this session. Do not stop after producing another plan.


1. PRODUCT WE ARE BUILDING

A simulated fly brain observes newly launched memecoins,
receives their market context through sensory stimulation,
chooses among eligible candidates, enters a paper position,
experiences the outcome, and carries the learned state into
subsequent decisions about other tokens.

Canonical loop:

PONS LAUNCHES / TRADES / MARKET STATE
    → CAUSAL MARKET CONTEXT
    → SENSORY ENCODING
    → EXISTING CONNECTOME SIMULATION
    → EXISTING NEURAL READOUT
    → CANDIDATE AND ACTION
    → PAPER EXECUTION
    → REALIZED NET OUTCOME
    → EPISODE-SPECIFIC REINFORCEMENT
    → PERSISTENT LEARNING
    → NEXT OPPORTUNITY

A token is selected because its neural response wins under
the documented decoder, not because we hardcoded its ticker,
promised someone exposure, or ranked it with another AI.

Names, symbols, images and promotional text are display
metadata. They are not instructions or predictive inputs.

The system must remain meaningful when the fly:
waits, loses, becomes less active, or chooses badly.

Do not force trades to make the demonstration exciting.


2. REUSE THE EXISTING STACK FIRST

The owner has another local project with an economical
Chainstack/RPC implementation.

Locate that implementation in the available local workspace.

Start with repository metadata, local project indexes and
likely source directories. Use targeted searches for:
Chainstack configuration references, RPC clients, getLogs,
event watchers, caches, request budgets and checkpoints.

Do not crawl the entire home directory or dump secret files.
Do not assume a project name or path is correct before reading it.

Inspect the donor project READ-ONLY.

Look for reusable components:
- HTTP/WSS clients and connection ownership;
- bounded backfill and adaptive log ranges;
- request counters and budgets;
- retry/backoff and rate limiting;
- block timestamp caches;
- event decoding and normalization;
- deduplication and database transactions;
- durable cursors and reconnect recovery;
- metrics, tests and operational scripts.

Create a short reuse table:

component | actual source | reuse/adapt/reject | reason | tests

Do not copy the whole donor application.

If the donor uses Solana/Yellowstone, reuse portable budgeting,
storage and recovery patterns where appropriate.
Do not pretend its subscriptions, event schemas or transaction
semantics are compatible with an EVM chain.

If it already has compatible EVM collection, adapt that code
instead of writing a second collector unnecessarily.

Keep the donor's source, database, runtime and budgets isolated.
Do not stop its services, migrate its database or consume its
reserved quota invisibly.

Never copy signing keys or entire .env files.

RPC access may use an explicitly configured existing endpoint
in the new process, with secrets redacted from output.

Document source commits and license obligations.

If no donor is accessible, report the exact search boundary.
Continue with the existing project's smallest compatible
adapter; do not claim reuse that did not happen.


3. PRESERVE THE WORKING FLY CORE

Reuse the accepted implementation of:
- anatomical, fast-transmission and modulatory graphs;
- corrected dopamine-path orientation;
- KC→MBON plasticity;
- episode eligibility and normalized updates;
- k=8 measurements and deterministic seed handling;
- neural decoder and explicit status distinctions;
- atomic checkpoints and journal recovery;
- paper accounting;
- event replay and observer contract.

Keep upstream/ and its audit unchanged.

Start the Pons experiment from the declared clean reference
checkpoint, not the IBM-trained suppressed checkpoint.

Create a new experiment identity and versioned Pons encoder.

Do not claim the IBM result established market-prediction skill.
It demonstrated implemented conditioning and behavior change;
the reported predictive tests did not demonstrate improvement.

Do not import an LLM, external classifier, alpha score or
technical-analysis strategy into the decision path.

Do not silently retune gain, thresholds or neuron membership
to manufacture activity on memecoins.


4. VERIFY THE ACTUAL PONS DEPLOYMENTS

Primary references:
https://docs.ponsfamily.com/
https://docs.ponsfamily.com/v2
https://www.ponsfamily.com/launchpad

Use official deployment information and verified contract
interfaces, checked against the configured RPC.

Do not hardcode remembered addresses or assume all Pons
launches share one market mechanism.

The documentation distinguishes protocol versions.
Resolve the version and market route of each supported launch.

Create a deployment manifest with:
- chain ID and network verification;
- factory/version;
- deployment block or bounded discovery start;
- ABI provenance;
- contract code hashes where practical;
- quote assets;
- market contracts and identifiers;
- applicable quote, fee and lifecycle rules.

Support a bounded, explicitly identified initial deployment.
Discover which deployment actually has the relevant launches.

Do not spend the wave implementing every historical version.
Recognize unsupported versions and mark them UNSUPPORTED;
never decode them with a convenient but wrong ABI.

Treat pool/curve transitions according to that deployment,
not according to a universal "graduation" assumption.

If a position's market route changes, retain the position and
resolve the new route or report it as temporarily unavailable.
Do not delete the exposure.

An existing Chainstack URL is not automatically the correct
network. Verify its chain before collection.

Do not bypass access controls or silently switch providers.
If required deployment evidence is unavailable, document the
specific missing evidence and isolate that adapter.


5. LOW-COST EVENT COLLECTION

Implement one collector feeding local canonical storage.

Prefer narrow factory/market event queries, shared connections,
incremental cursors and cached state over repeated reads of
every token.

Do not poll every pool independently at high frequency.
Do not subscribe to the entire chain by default.

Use a durable cursor:
chain ID + block number/hash + transaction index + log index.

Persist raw evidence and normalized events.
Deduplicate deliveries across HTTP backfill and WSS.

Handle:
- reconnect gaps;
- duplicate and out-of-order messages;
- reverted transactions;
- removed logs and chain reorganizations;
- partial processing and restart.

Distinguish fast observed events from the finalized/confirmed
events permitted to drive canonical learning.

Define the chain-specific finality policy explicitly.
A rollback must not leave the brain trained on orphaned events.

Use bounded HTTP backfill and live collection through the same
normalization path. Historical replay must not require repeatedly
fetching the same data.

Before network work, record finite limits:
- RPC methods/requests per wave and per operational window;
- concurrent requests;
- tracked market count;
- backfill range;
- retries.

Reuse stricter existing owner-approved limits.

Count batch elements, retries and delivered subscription
messages according to the endpoint's charging model.
Do not assume a persistent WebSocket is free.

At the budget limit, persist progress and stop collection
cleanly. Never switch to another paid provider to evade a cap.

A request budget is not a trading signal.

Report measured calls, events, cache hits, errors and block lag.
No subscription purchase or unlimited backfill is authorized.


6. CAUSAL MEMECOIN CONTEXT

Derive observations from verified events and state available
at the decision cutoff.

Initial candidate measurements:
- token age;
- recent signed price path and returns;
- quote-denominated traded volume;
- buy/sell flow imbalance;
- trade arrival rate;
- realized volatility and drawdown;
- executable depth or size-specific price impact, where
  supported by the validated market adapter;
- freshness and data completeness.

Start with a small documented subset actually reconstructible
from the supported deployment.

Do not invent absent measurements or add expensive wallet
clustering to this wave.

Use token address + chain ID as identity.
Use a common supported quote asset for the initial universe.

Do not compare raw volume in ETH against raw volume in another
quote token as though the units were identical.

Do not claim a USD value without a sourced conversion at the
relevant timestamp. Quote-asset accounting is sufficient.

Validate decimals, token ordering, signed amounts, fees and
integer precision.

Separate:
- last trade price;
- marginal pool/curve price;
- executable amount-out for our proposed size.

They are not interchangeable.

No-trade intervals, unavailable state and actual price drops
are different conditions. Missing data is not a zero price.

In replay, never use current/latest state to answer a
historical decision.

If historical state cannot be reconstructed or queried within
the budget, report the missing coverage rather than fabricating
quotes.


7. CANDIDATE ADMISSION IS NOT A HIDDEN TRADER

Use objective, versioned admission rules for:
- supported deployment and quote asset;
- sufficient past observations;
- valid current market state;
- availability of a modeled executable route.

Keep discovery records for failed, inactive and ungraduated
launches. Do not build the dataset from today's survivors.

Do not select candidates using future return, eventual
graduation, current popularity or a preferred ticker.

Use the existing maximum of six neural candidates per round.

If more qualify, use a documented rotation policy independent
of expected profitability. Record omitted candidates and why.

Every selected candidate receives equivalent measurement
conditions and the same learned-state version.

Preserve order and metadata-renaming invariance.

No manual preference for PONZO, PONS or any other token.

Admission, neural rejection and execution rejection must have
different statuses and reason codes.


8. SENSORY TRANSLATION AND MULTIMODAL EXTENSION

The primary deliverable must work through the olfactory
learning path already tested in this repository.

Do not block the Pons integration on rebuilding all senses.

Create a versioned SensoryEncoder interface with explicit
modality outputs, so verified visual input can be added
without rewriting market collection or execution.

For the first working Pons mapping:
- encode measured context as reproducible temporal patterns;
- preserve the distinction between rising and falling prices;
- keep normalization causal;
- document every feature/channel mapping and rate bound;
- keep absent data distinguishable from neutral measurements.

A high-volume token is not automatically "good".
A falling price is not automatically a punishment.
Market observation and outcome reinforcement remain separate.

Do not give a feature arbitrary extra amplitude merely because
we think it is important.

More channels or different representations are allowed as
declared encoder design choices, not as proven biological
importance weights.

Measure silence, saturation and response discrimination across
the declared Pons input range without optimizing PnL.

Add the visual adapter only after inspecting the actual visual
path available in our graph and upstream implementation.

An actual visual adapter must:
- stimulate documented visual input populations;
- encode price-path information, not trading recommendations;
- expose its real stimuli and measured neural response;
- show whether that input reaches the readout/learning path;
- be checked with the visual input disabled on matched inputs.

Drawing a chart or animated eye is not a visual neural input.

Do not claim multimodal learning unless the integrated path
was exercised and tested.

Do not route price drops into an innate escape circuit simply
to force SELL. Do not directly stimulate output populations
and describe that as perception.

Taste, touch, looming and additional modalities remain explicit
extension points unless genuinely implemented and verified.

A working olfactory Pons loop is an acceptable first delivery.
An unverified multimodal claim is not.


9. MEMECOIN EPISODES AND CONTINUOUS LEARNING

This is a new environment, not IBM with different tickers.

Implement:
REPLAY_PAPER — chronological recorded Pons events.
LIVE_PAPER — newly received Pons events.

Support LEARN and FROZEN explicitly.

The bounded demonstration should use LEARN, carrying one
learned brain across successive tokens and outcomes.

Do not reset memory when a new token appears or after a loss.

Initial versioned engineering defaults:
- decision cadence: 30 seconds;
- maximum candidates per round: 6;
- one open paper position;
- fixed holding horizon: 15 minutes;
- explicit fixed paper sizing in the configured quote asset.

Fifteen minutes is a product-test setting, not a scientifically
optimal memecoin horizon. Do not carry over IBM's 90 minutes.

Record these choices before looking at Pons outcomes.
Do not search multiple horizons for a profitable demonstration.

Entry remains controlled by the neural decoder.

Keep receiving and showing context while a position is open:
price movement, position mark and neural response.

For this first policy, record early SELL signals but close at
the fixed horizon. Label closure POLICY_CLOSE.

Training and evaluation labels must use the same entry,
horizon, actual modeled costs and settlement conventions.

Reinforce the entry's stored eligible experience once.
Do not reinforce whichever observation was processed last.

Reward uses the settled net outcome, not unrealized gains.
Do not provide interim reward merely because a position is up.

Use the existing normalized learning rule. Do not increase
reward strength to make the learning animation more dramatic.

Preserve NO_RESPONSE. Do not force exploration purchases
behind the brain's back.

More observed launches are not automatically more independent
training experiences. Report completed episodes honestly.

Repeated replay of the same data must be identified as repeated
exposure, not new market history.

If later evaluating generalization, split by launch time/token
cohort, not randomly interleaved observations of the same launch.


10. PAPER FILLS MUST REPRESENT THE MARKET

Do not reuse IBM's flat 20-bps cost as Pons's cost.

For each supported market route, implement or reuse a verified
size-dependent quote calculation with its actual fee rules,
rounding and state requirements.

Validate sampled calculations against an available authoritative
quote method or known settled trade evidence.

Do not substitute constant-product reserve math for a different
pool/curve mechanism.

Include applicable protocol fees, creator taxes, price impact
and explicitly modeled execution costs without double counting.

Use exact integer amounts for on-chain quantities.

Apply declared observation/decision/execution latency.
Paper fills cannot use information or prices available only
before the decision was actually possible.

For historical replay, require the needed historical state.
For live paper, use a recorded eligible post-decision state.

These remain simulated fills, not real transactions.

Document that the paper position does not change the subsequent
recorded public market. Do not claim to simulate audience
copying or the fly's market impact on future external orders.

No sell quote can mean:
missing data, temporary route transition, no executable depth,
or another explicit condition.

Do not treat an RPC error as a -100% trade.
Do not treat an illiquid position as successfully sold at
the last displayed price.

Retain unresolved positions and distinguish infrastructure
failure from an observed economic loss.

No reward until the declared settlement/write-down policy
actually supplies a valid outcome.


11. ACTIVE WORKER AND OBSERVER CONTRACT

Reuse the existing journal, recovery and viewer contract.

A single worker owns collection-driven decisions and learning.
Viewer connections must never create extra brains or RPC
subscriptions.

Support bounded reconnect, health status and graceful restart.

Record enough evidence to reconstruct:
- eligible candidate set;
- exact observations and sensory inputs;
- neural scores and chosen token;
- execution-policy result;
- quotes/fills and costs;
- linked outcome and learning update;
- before/after learned-state hashes.

Continue serving the existing observer read-only.

Visual design belongs to GPT/Astra.
Only add the backend fields and minimal compatibility changes
needed for Pons runs.

Expose:
PONS / REPLAY or LIVE DATA / PAPER / LEARN or FROZEN.

A signal is not a fill.
A paper buy is not an on-chain transaction.
A current data connection is not proof of fresh usable data.

No fake spikes, fills, profits, losses or learning events.

No frontend control may secretly select the winning token.

Leave real-money execution behind a separate future adapter.
It is postponed, not removed from the product roadmap.

This wave must not sign, approve, broadcast, move funds,
claim fees or create a token.


12. ONE BOUNDED IMPLEMENTATION WAVE

Execute in this order:

A. Inspect the current project and donor stack.
   Record the reuse decisions and pivot amendment.

B. Verify one relevant Pons deployment.
   Build the budgeted collector and canonical event adapter.

C. Reconstruct a bounded genuine Pons dataset.
   Connect it to the existing sensory/brain/paper/learning loop.

D. Run a short chronological demonstration with genuine
   recorded Pons observations and new run identities.

E. Exercise live collection and the active observer when the
   configured endpoint is available, using finite stop limits.

Do not end with only an architecture document if the required
inputs are accessible.

Do not turn this into another weeks-long search for alpha.
Profitability and statistically significant prediction are not
engineering acceptance criteria.

If a genuine blocker prevents part of the integration,
complete the independent pieces and name the blocked link.

Do not replace missing Pons evidence with synthetic data and
declare the real integration complete.

The absence of a BUY is not permission to manipulate inputs.
Use explicitly labeled fixtures to test lifecycle mechanics
and report what actually occurred on real observations.


13. TESTS AND CLOSING EVIDENCE

Add focused tests for:
- correct chain and deployment version;
- incompatible donor-protocol rejection;
- budgets including retries and subscription deliveries;
- event deduplication, gaps, reorgs and restart;
- decimals, units, trade direction and price calculation;
- historical-state causality;
- candidate admission and fair rotation;
- metadata/order invariance;
- sensory determinism and invalid-input handling;
- no hidden market strategy in the decoder;
- exact-size quotes, fees and unavailable exits;
- entry/outcome target alignment;
- one normalized update per settled episode;
- no cross-token credit contamination;
- preserved learning across restart;
- FROZEN with unchanged weights;
- no signing or order-broadcast network paths;
- observer projection fidelity.

Keep previous experiment artifacts and upstream-defect tests.

Run the full regression gate twice at closure.
Do not weaken assertions simply to keep a test count.

Deliver:
- actual reuse table with source paths and commits;
- verified Pons deployment manifest;
- bounded data and RPC-consumption report;
- working collector and market adapter;
- versioned Pons sensory/paper-policy configuration;
- genuine Pons replay evidence;
- any completed decision/outcome/learning episodes;
- live collection status, clearly separated from replay;
- exact start/stop/status commands;
- observer-compatible events;
- known unsupported versions/modalities;
- tests, commits and working-tree state;
- updated the session log with the next concrete step.

Separate these conclusions:
1. Integration works or has a named blocker.
2. The brain produced the observed behavior.
3. Learning updated the declared eligible state.
4. Predictive usefulness is demonstrated or not demonstrated.

Never merge those four claims.

START WITH THE EXISTING CODE.
REUSE WHAT IS VERIFIED.
ADAPT WHAT IS NETWORK-SPECIFIC.
BUILD THE MISSING PONS ENVIRONMENT.
DO NOT RETURN TO IBM/ALPACA.

### Owner rationale recorded with the amendment (2026-09-12, from Portuguese)

The prompt above moves the queue to Pons memecoins, orders the reuse of the existing Chainstack infrastructure and preserves the brain already built. IBM/Alpaca leave the next implementation. Two concrete cautions were included by the owner: validate which Pons version is being integrated, because the documentation describes different mechanisms; and measure RPC consumption, because messages received over WebSocket may also count as requests on Chainstack — swapping polling for WebSocket and calling it cheap is not enough. What the prompt demands is the fly receiving real Pons memecoins and going through the decision-and-learning cycle, using what already exists, with no further reconstruction of the project and without pretending an animation is a new sense. The owner also said, after sending the prompt, that parts of it were drafted by the visual-track collaborator ("Astra") and may be wrong, and that the reviewer must confirm them before following them blindly. The owner authorised autonomous execution of the whole wave in this session and lifted the token-spend ceiling for it.

**Supersession.** The D10 item queued by the (i) HANDOFF block and its four owner questions (Alpaca/IBM live market with paper execution) are **SUPERSEDED** by this amendment. Their history stays in the session log and in this file. The IBM experiments (D5–D9(b)) remain historical evidence and their artifacts stay untouched.

### Fable addenda (reviewer, 2026-09-12) — binding for the D10 wave

**What was verified before these addenda were written, and what the amendment got wrong or left open.** The amendment was drafted partly by the visual-track collaborator and the owner asked that it be confirmed, not followed blindly. The reviewer checked the following against primary evidence; everything below that contradicts the amendment overrides it.

- **Pons versions and mechanisms (verified at docs.ponsfamily.com, docs.ponsfamily.com/v2 and github.com/ponsdotdev/ponsfamily).** Chain: Robinhood Chain, chain ID **4663**, native asset ETH. The root documentation describes **v1**: a Uniswap **V3** pool per launch with a 1 % fee tier, WETH quote (`0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73`), fixed 1e9 supply, graduation when the locked pool holds 4.2 ETH, **no migration**, "active factory" `0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB` and a "legacy factory" `0x0c37a24F5D23A486FA692d1500881d698B1F77a4`. The `/v2` documentation describes **v2**: one constant-product **bonding curve per launch** with a phantom (virtual) quote reserve, a base trade fee shared between protocol, creator and optional buyback, an optional capped creator tax, a **snipe tax on buys starting at 99 % and decaying to zero over the first 5 seconds**, graduation when the tradable allocation is sold, then a **Uniswap V4** pool with a "Meme Hook" and permanently locked liquidity; factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`, hook `0xE5e702641Ea86F4ae6cC3cDaeD2B886f976Be044`, quote asset ETH by default or any token Pons has approved. The v2 page says "v2 is the current active version", that "the v1 protocol continues to operate", and that **"public launches are closed, so only whitelisted addresses can create a token for now"**. The repository is MIT for first-party contracts, GPL-2.0-or-later for `PonsTickMath.sol`. The launchpad page was not used as evidence (it is a user interface, not a deployment record). **Consequence:** the two versions are different market mechanisms with different factories; nothing may decode one with the other's ABI, and the "whitelisted only" statement must be measured against the factory's actual recent launch rate, not assumed either way.
- **The donor (verified read-only at `~/Documentos/PONS`).** It is the owner's private Pons radar: TypeScript 7 / Node 22 / PostgreSQL 16 / `viem` 2.56.3 / `zod` 4.5.4, **not a git repository** (no commit to cite; files are identified by sha256). Its RPC credential is read at runtime, by key name only, from `~/Documentos/stockroom/.env` (`CHAINSTACK_RPC_HTTPS_KEYED`; a `CHAINSTACK_RPC_WSS_KEYED` key also exists by name). Its PostgreSQL instance on port 55432 is **not running** and its `data/` and `artifacts/` (302 MiB and 713 MiB) are on disk. It already holds: a deployment manifest (`config/deployments.json`: chain 4663, `pons-v1` = `0xa5aa…feb` code hash `0x0a62…91d4`, `pons-v2` = `0x7ed5…ec7e` code hash `0x89a2…7d84`, LONG pending), event evidence pinned to source commit `8b9bf371030279133017b5c1b713823f5889c5d2` and Sourcify match `43289536` (`config/event-evidence.json`), the frozen curve sources (`docs/evidence/PonsV2BondingCurve.sourcify.sol`, `PonsV2BondingCurveMath.sol`, sha256 in `config/quote-deployments.json`), an integer-exact port of the curve quote (`src/curve-quotes.ts`, tested against `test/fixtures/pons-quotes-{curve,transition,v4}.json`), a bounded RPC client with a method allowlist, a per-run and per-day request budget, HTTP 429 / quota halt and **no automatic retry or fallback** (`src/rpc.ts`), a reorg-aware chunk/checkpoint store (`sql/001_init.sql`), and — decisive for this wave — **hash-anchored raw datasets already collected**: `artifacts/curve-simulation/batch-*.json` holds, for **546 native-ETH v2 launches** in two one-hour windows (2026-09-08 06:00–07:00 UTC and 2026-09-09 05:00–06:00 UTC), the raw factory and curve logs, the block headers with timestamps, the `eth_getLogs` ranges as returned, the initial curve state reads per token (`calibrations`) and the head hash everything is anchored to; the donor's own report states the reserves reconstructed from these events were checked against RPC snapshots of every curve. **Consequence:** "adapt the donor's EVM collector" cannot mean running or importing TypeScript into a Python project whose only runtime dependencies are numpy/scipy/pandas/pyarrow. Reuse here means (i) importing the donor's raw evidence through the new normalisation path, (ii) copying its manifests, ABIs, evidence files and fixtures with their sha256, (iii) porting its budget, cursor, reorg and curve-quote semantics to Python and proving the port against its fixtures. The reuse table must say exactly this; it must not claim code reuse that did not happen.
- **Chainstack metering (verified at docs.chainstack.com/docs/request-units).** "Each JSON-RPC call counts as one request, regardless of how much data the response contains." For WebSocket: "Setting up the subscription counts as one request — and then each push notification the node sends to you counts as one more request." Reads 127 or more blocks behind the tip (`eth_getLogs`, `eth_call`, `eth_getBlockByNumber`) are billed as archive at **2 request units**; recent reads at 1. **Consequence:** the owner's caution is correct. With several launches per minute and hundreds of live curves, a `logs` subscription would deliver thousands of billed pushes per hour, while one `eth_getLogs` over an address list per 30-second tick is one unit. **This wave implements HTTP polling only**, at the decision cadence, and reports the measured request count together with the computed WSS-equivalent (subscription pushes = observed events + block headers) so the comparison is a number, not an opinion. Anything ≥ 127 blocks behind the tip is counted at 2 units in the ledger.
- **Flytrade's actual seams (verified in the tree at `5dc5704`).** `flytrade.encoder.MarketToSensoryEncoder` takes a `features` tuple and assigns **two glomerular channels per feature** from `sensory.candidate_glomeruli`, so rising and falling values are already distinct channels; `MarketObservation` carries `status`, `raw`, `normalized`, `z` and a `stable_id`; `experiments/historical/run.py::run_branch` is welded to minute-bar sessions (`series`, `parts`, `partitions`, `day`, `horizon.locate`). **Consequence:** the Pons loop is a **new driver** that reuses the brain, the readout (k = 8, `comparison_v1`), the decoder, the journal, the records, the execution accounting and the observer, and does **not** reuse `run_branch`. The IBM normaliser (a 60-bar causal z-score needing 81 bars of history) cannot apply to a token that is ninety seconds old; the Pons encoder needs declared fixed scales instead (addendum 9).
- **Docs robinhood.com was unreachable (DNS) at review time.** Chain ID 4663 is confirmed by the Pons documentation, the Pons repository and the donor manifest, and is re-verified by `eth_chainId` before any collection. Block interval and tag support (`safe` / `finalized`) are measured, not remembered (addendum 7).

**Corrections to the amendment, binding.** (a) Donor reuse is data, configuration, fixtures and ported semantics, never a TypeScript runtime or a second copy of its database. (b) No WebSocket collection in this wave; consumption is measured and the WSS-equivalent computed. (c) The visual adapter and every non-olfactory modality are **out of this wave**; the `SensoryEncoder` interface exposes the extension point and nothing else. (d) The **v1 route (Uniswap V3) and the v2 post-graduation route (Uniswap V4) are UNSUPPORTED for pricing in this wave**; they are recognised, recorded and never decoded with the curve ABI. A position whose curve completes before its horizon is retained as `UNRESOLVED` with reason `ROUTE_TRANSITION`, settles no outcome and teaches nothing — it is neither a loss nor a win. (e) The genuine replay dataset is the donor's raw evidence imported through the same normalisation path the live collector uses, at **zero RPC cost**; running the same two hours twice is repeated exposure and is labelled as such. (f) "Label closure POLICY_CLOSE": the existing member `CloseReason.POLICY_CLOSE_FIXED_HOLD` is that label for a fixed-hold close and is reused as is; the summary counts it under `policy_close` exactly as D9(b) does.

**1. Identity and layout.** Wave **D10**. Chain code lives in a new package `flytrade/pons/` (proposed modules: `rpc.py`, `budget.py`, `manifest.py`, `abi.py`, `collector.py`, `storage.py`, `curve.py`, `context.py`, `encoder.py`, `admission.py`, `paper.py`, `loop.py`); experiment files in `experiments/d10/` (`PLAN.md`, `config.json`, `deployments.json`, `REUSE.md`, `import_donor.py`, `run.py`, `probe.py`, `report.py`, `runs/`); tests in `tests/d10/`. `upstream/`, `tests/upstream_audit/`, `experiments/d5`…`d9b`, `experiments/historical/runs`, `data/market` and every committed IBM artifact stay byte-identical; the wave proves it with `git diff --stat 5dc5704 -- upstream tests/upstream_audit experiments/d7 experiments/d8 experiments/d9b experiments/historical/runs data` empty at close. Changes to `flytrade/*.py` outside `flytrade/pons/` are limited to what the new driver needs (new enum members, new optional fields) and are listed one by one in the HANDOFF block.

**2. Register-then-compute, unchanged.** `experiments/d10/PLAN.md` and `config.json` are committed **alone**, before any run and before any Pons outcome is looked at. The config records, verbatim: cadence 30 s; ≤ 6 candidates per round; one open position; horizon **15 minutes = 30 rounds**; paper size **0.01 ETH = 10 000 000 000 000 000 wei**; latency; gas constants and their source; feature list, scales and channel map; admission and rotation rules; budgets; finality depth; the clean reference checkpoint digest; the sha256 of every donor file imported. Nothing in it may be changed after the first run except by a declared deviation.

**3. Deployment manifest (`experiments/d10/deployments.json`), verified against the RPC before collection, ≤ 20 requests.** Entries: `pons-v2` (factory `0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e`, adapter `curve`, status `verified-code-hash` only if `keccak256(eth_getCode)` equals the donor's `0x89a27da6f703e0a7cdd4f233e7cb57604ff75b164530962d3ff7cf8483a67d84`, else `code-hash-mismatch` and the wave stops to report); `pons-v1` (factory `0xa5aab3f0c6eeadf30ef1d3eb997108e976351feb`, status `UNSUPPORTED`, reason "Uniswap V3 route, not priced this wave"); `pons-v1-legacy` (`0x0c37a24f5d23a486fa692d1500881d698b1f77a4`, `UNSUPPORTED`); `uniswap-v4-post-graduation` (hook `0xe5e702641ea86f4ae6cc3cdaed2b886f976be044`, quoter `0x8dc178efb8111bb0973dd9d722ebeff267c98f94` with the donor's Sourcify evidence, `UNSUPPORTED-this-wave`). Chain: `eth_chainId` must return 4663 or nothing else runs. ABI provenance: the donor's `config/event-evidence.json` and `config/pons-v2-read-abi.json` copied to `experiments/d10/evidence/` with sha256, plus the topic0 of every decoded event recomputed by keccak-256 from its declaration and compared with the evidence file in a test. Quote asset: **native ETH only** (`pairToken == 0x0000000000000000000000000000000000000000`); any other pair token is recorded and `NOT_ADMITTED(QUOTE_UNSUPPORTED)`. Discovery start for live: the head at start minus a bounded backfill (addendum 6); no genesis scan.

**4. RPC client.** Standard-library HTTP (`urllib`), JSON-RPC 2.0, one endpoint read at runtime from the file and key named in config (`RPC_ENV_FILE`, `RPC_ENV_KEY`, defaults as the donor's), never printed, never logged, never written to any artifact — every artifact and log line masks the host and key (tested). **Method allowlist:** `eth_chainId`, `eth_blockNumber`, `eth_getBlockByNumber`, `eth_getLogs`, `eth_getCode`, `eth_call`; every other method raises `RPC_METHOD_NOT_ALLOWED` before any socket is opened. This allowlist, and the absence of any key material or signing code in `flytrade/`, is the "no signing or broadcast path" proof, tested by attempting `eth_sendRawTransaction`, `eth_sendTransaction`, `eth_sign`, `personal_sign`, `eth_accounts`. Timeout 15 s. **No automatic retry, no fallback provider, no local node.** HTTP 429 or a quota message in the JSON-RPC error halts the process with the ledger persisted. keccak-256 is needed for topic0 recomputation and code-hash verification; add **`pycryptodome`** pinned, used only for `Crypto.Hash.keccak`, with a test that `keccak256(b"")` is `c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470`. No `web3`, no `eth-abi`; the handful of static-layout events are decoded by hand (topics + 32-byte words) with shape checks as strict as the donor's (`ABI_SHAPE_MISMATCH` on extra topics or trailing data).

**5. Budget and ledger, before any network work.** Wave cap **10 000 requests**; per process run **≤ 5 000** (config); per calendar day **≤ 10 000**, persisted in `experiments/d10/rpc_ledger.json` (attempts including errors, archive-weighted units, by method, by day, by run id) so a restart does not reset it. Concurrency **1**. Retries **0**. Verification ≤ 20 requests (addendum 3); live exercise ≤ 3 000 requests or 60 minutes wall clock, whichever first (addendum 15). Reaching any cap persists the cursor and ledger and exits with `RPC_BUDGET_STOP`; nothing else may switch providers. The ledger and the block lag (head − cursor, in blocks and seconds) are reported. The replay dataset costs 0 requests by construction (addendum 8).

**6. Collector.** One process. Durable cursor `(chain_id, block_number, block_hash, tx_index, log_index)` plus the hash of the last **confirmed** block, persisted atomically with the events (write-temp-rename, as the existing checkpoints). Per tick: `eth_getBlockByNumber("latest")`; one `eth_getLogs` over `[cursor+1, head]` for the factory (`TokenLaunched` and the other factory events) and one over the same range for the address list of **tracked curves**; range chunking bounded to the donor's 25-block chunks only when a range is larger than one tick's worth. Tracked = curves launched within the last 60 minutes, or holding a position, minus curves whose `CurveCompleted` was seen (they leave the tracked set and are recorded `ROUTE_TRANSITION`). Raw logs are persisted as received (`raw.jsonl`) and normalised events beside them (`events.jsonl`), both under `experiments/d10/runs/<run>/chain/`. Dedup key = `block_hash:tx_hash:log_index` (the donor's `logId`). Out-of-order delivery is sorted by `(block_number, tx_index, log_index)` before normalisation. A log with `removed: true`, or a log whose block hash no longer matches the stored header, marks the affected events `ORPHANED`, rewinds the cursor to the last confirmed block and re-reads; orphaned events are kept in `raw.jsonl`, never deleted, and never feed context again. Restart resumes from the cursor; a restart mid-tick reproduces the same normalised stream (tested with a scripted RPC). Initial curve state (`getReserves`, `realQuoteReserve`, `sellableTokens`, `feeBps`, `creatorTaxBps`, snipe parameters, `graduationThreshold`) is read by `eth_call` **once per curve, lazily, on first admission**, at the launch block, and cached; a curve that never reaches admission costs no state read. Live backfill at start: at most the last 60 minutes of blocks, so tracked curves have their history.

**7. Finality policy, declared before the run.** Robinhood Chain is an Arbitrum Nitro chain (the donor runs a `nitro-robinhood` node). The wave measures the median block interval from the donor's headers, then sets **`confirm_depth` = the number of blocks in 60 seconds** (recorded in config), and checks once whether the endpoint answers `eth_getBlockByNumber("safe")`; if it does, a block is confirmed when it is ≤ `safe` **and** ≥ `confirm_depth` behind head; if not, depth alone. **Decisions** use the fast stream (`latest`). **OUTCOME and LEARNING** are written only when the entry-fill block and the horizon block are both confirmed and their stored hashes still match a fresh `eth_getBlockByNumber` of those numbers (2 requests per settlement); until then the episode is `PENDING_CONFIRMATION`, no reward. A rollback that invalidates an entry or exit after the fact therefore cannot have taught anything by construction; if it invalidates events before settlement the episode becomes `ORPHANED` and settles nothing. The replay dataset is days old and hash-anchored to the donor's head; it is confirmed by age and the same code path is exercised with `confirm_depth` satisfied trivially.

**8. The genuine replay dataset, zero RPC.** `experiments/d10/import_donor.py` reads, read-only, `~/Documentos/PONS/artifacts/curve-simulation/batch-*.json` and the two `micro-cohort*/results.json` (for the launch windows), verifies internal consistency (unique log ids; every event's block hash present in the headers; every token's calibration present; ranges' payloads contain the events; head hash consistent), and writes `data/pons/d10-replay-v1/` (`raw.jsonl`, `events.jsonl`, `headers.jsonl`, `initial_states.json`, `MANIFEST.json` with the sha256 of every source file and of every output). `data/*/` is git-ignored by the existing rule; provenance goes into `data/MANIFEST.md` exactly as the connectome and Kibot entries do, and the sha256s are repeated in `experiments/d10/config.json`. The import goes through **the same** `normalise(raw_log) → event` function the live collector uses, so replay and live are one code path. Curve state per token over time is **reconstructed from events** starting from the calibrated initial state (`CurveBuy`: quote in net of fee and tax raises both reserves, tokens out lowers token reserve and sellable; `CurveSell` the reverse; `BuybackLocked` moves reserves; `FeesSwept`, `SnipeTaxCharged`, `SnipeTaxExempted` and the administrative events change nothing in reserves — the donor's rules); the reconstruction is validated against the donor's per-token calibration reads and, where the batches include later state reads, against those (the donor reports this check passed for all 546). Coverage per token = launch → the earlier of `CurveCompleted` and the end of its window; the config records it. On-chain public data, no licence limits; the donor's artifacts are the owner's own.

**9. Context features and the Pons encoder, versioned `pons_context_v1` / `pons_encoder_v1`.** Identity: `(chain_id, token address)`; `stable_id` from the existing `Universe`. All features are computed **at the cutoff** from confirmed-or-fast events (decisions may use fast events; addendum 7 governs settlement) with **no access to anything after the cutoff** (tested by asserting that truncating the stream at the cutoff gives the same vector). Features, in this order, each with a declared fixed scale `s` and `normalized = tanh(raw / s)` (the existing tanh convention, `Z_SCALE` semantics): `age` (seconds since the launch block); `ret_30s`, `ret_2m`, `ret_5m` (log change of the **marginal curve price** `quoteReserve / tokenReserve`, phantom included, over the window, 0 when the window predates the launch); `flow_imb_2m` ((net quote in from buys − gross quote out from sells) / (their sum) over 2 minutes, in [−1, 1], 0 with no trades); `trade_rate_2m` (trades per minute over 2 minutes); `rv_2m` (standard deviation of per-trade log marginal-price changes over 2 minutes); `drawdown_5m` (log distance of the current marginal price below its 5-minute maximum, ≤ 0). `candidate_glomeruli` decides how many features fit at two channels each; if fewer than 16 channels exist, features are dropped **from the end of this list** and the config says which. Scales are set from the donor's cohort statistics **on the 09-08 window only, before any Pons outcome is looked at**, rounded, and written in the config; they are never refitted. **Absent versus neutral:** a token with age < 60 s or fewer than 3 trades, or with an inconsistent reconstructed state, has `ObservationStatus` unusable, is **not presented** and the reason is recorded — that is the existing distinction between "no stimulus" and "a zero-valued stimulus". A window with no trades is a valid measurement (rate 0, imbalance 0), not an absence. Last trade price, marginal price and executable amount-out are three separate fields in the observation record; only the marginal price enters features; the executable amount-out for 0.01 ETH is recorded for the chosen candidate at decision time (from the reconstructed state, one formula evaluation, no request). The `SensoryEncoder` interface (`flytrade/pons/encoder.py`) returns `{"olfactory": Stimulus}` and nothing else; `visual`, `taste`, `mechanosensory` are named as unimplemented extension points in the docstring and nowhere else. **Silence and saturation probe** (`experiments/d10/probe.py`): the clean reference brain, k = 8, presented with the 2^n corners at ±1, the centre and ±0.5 on each axis alone, reporting response rate, fraction of saturated presentations and the pairwise discrimination of the D7 kind on a handful of pairs; no PnL anywhere in it.

**10. Admission `admission_v1` and rotation, objective and versioned.** Admitted iff: deployment `pons-v2`; quote native ETH; observation usable (addendum 9); curve not completed at cutoff; reconstructed state valid (`sellableTokens > 0`, `realQuoteReserve > 0`); the paper buy of 0.01 ETH would **not** exhaust the curve; and, in replay, `cutoff + latency + 900 s` lies inside the token's coverage (else `NOT_ADMITTED(COVERAGE)`). Every launch, admitted or not, gets a `DISCOVERY` record with its reason codes; the dataset is not survivors. If more than 6 qualify: order by rounds since last presentation (descending), then launch block, then log index, then address — round-robin, blind to price, volume, flow and outcome; the omitted are recorded `ROTATED`. Admission statuses (`NOT_ADMITTED(*)`), neural statuses (`WAIT`, `NO_RESPONSE`, `SELL` while flat) and execution rejections (`RejectReason.*`) are three distinct vocabularies, as they already are.

**11. The loop (`flytrade/pons/loop.py`, driven by `experiments/d10/run.py`).** Modes `REPLAY_PAPER` (virtual clock stepping 30 s over the dataset's time span, events admitted only up to the cutoff) and `LIVE_PAPER` (wall clock, one tick per 30 s, cutoff = the timestamp of the latest block seen); learning `LEARN` or `FROZEN` (frozen: digest unchanged before and after, `settled_frozen` counted, credit accepted 0 — the D9(b) convention). Per tick: advance cursor → update reconstructed states → context for tracked tokens → admission → rotation → ≤ 6 candidates through the existing `ComparisonReadoutPolicy` (k = 8, `comparison_v1` seeds keyed by `observation_id` and `stable_id`, so **order and metadata invariance hold by construction** and are tested by shuffling and renaming) → existing decoder → one round record with every candidate's scores → execution policy: one position; BUY opens at the paper fill (addendum 12); a decoded SELL while holding is `RejectReason.FIXED_HOLD` and closes nothing; the position closes at `entry_fill_time + 900 s` with `CloseReason.POLICY_CLOSE_FIXED_HOLD`; WAIT and NO_RESPONSE are recorded as today. While a position is open, every tick still records the chosen token's context, the position mark (exit quote of the exact position at the reconstructed state, a mark, never a reward) and the neural response of the candidates. Settlement: OUTCOME after the confirmation rule; LEARNING once per episode through the existing normalised rule, credited to **the entry's stored eligibility trace** by episode id (the existing machinery; 30 intervening rounds are inside the 90 D9(b) proved); `valence` = sign of the net outcome, `amount` exactly as the existing rule derives it from the outcome — the plan states the mapping in one sentence and adds no scaling constant. No interim reward, no reset on new tokens or after losses, memory carried across tokens and across a restart (the mid-run restart test of D5/D6 is repeated here: kill after a settled episode, resume, gains restored exactly).

**12. Paper market adapter for the curve route (`flytrade/pons/curve.py`, `paper.py`).** Integer-exact Python port of the donor's `quoteCurveBuy` / `quoteCurveSell` / round-trip semantics, themselves a port of the frozen `PonsV2BondingCurveMath.sol` (copied to `experiments/d10/evidence/` with sha256; MIT attribution added to `NOTICE.md`): base fee, creator tax and the snipe tax with its cap and time decay (computed from the fill block timestamp against the launch timestamp, so it is zero after 5 s but never assumed zero), partial fill with refund when the buy would exhaust the curve, `QUOTE_EXCEEDS_REAL_RESERVE` and dust checks on sells. **Validation:** the tests reproduce the donor's fixture numbers (`test/fixtures/pons-quotes-curve.json`, copied) bit for bit, and reproduce at least three actual settled `CurveBuy` / `CurveSell` events from the replay dataset (quote in, fee, tax, tokens out) from the reconstructed pre-trade state — settled trade evidence, as the amendment asks. **Fill rule:** a decision at cutoff `t` fills at the reconstructed state of the first block with timestamp ≥ `t + latency`, latency **2 s** declared; the position's own reserve delta is carried (the donor's `ownNet`) so its exit quote sees its own impact plus the external flow that actually happened; the exit at `t_entry + 900 s` uses the same rule. **Gas:** three declared constants (buy, approval, sell) taken from the donor's calibration medians in `artifacts/curve-simulation` (40 buy and 40 sell receipts), recorded in config with their source; `net = quote_out − spent − gas`. The paper position never changes the recorded public market and the report says so. **Unavailable exits:** curve completed before the horizon → `UNRESOLVED(ROUTE_TRANSITION)`; missing coverage → `UNRESOLVED(COVERAGE)`; an RPC failure during live settlement → `PENDING_CONFIRMATION` retried on later ticks within the budget, never a loss. `FEE_BPS` and `SLIPPAGE_BPS` of `flytrade/execution.py` are **not used** on this route; the accounting identity `gross − fees − slippage = net` of `Account` is kept by writing the curve fees and tax into `fees` and the price impact into `slippage`, so the existing invariant tests still hold.

**13. Records and observer.** Reuse the existing `EventType` kinds; add a new kind only if no existing one fits (`DISCOVERY` is expected to be new). Every D10 record carries `venue: "PONS"`, `chain_id: 4663`, `mode`, `learning`, and chain identifiers (`token`, `curve`, `block_number`, `block_hash`, `tx_hash`, `log_index`) where an event has them. `records._compact` drops the new fields for the old projections, so the five committed historical/D7 projections and every D9(b) projection stay **byte-identical** before and after (asserted). The observer gains a third wave root `D10` beside `D5/D6`, `D7`, `D9(b)`, listing runs with `PONS / REPLAY|LIVE / PAPER / LEARN|FROZEN` in `/api/runs` and `/api/summary`, and serves `/api/presentation` for D10 branches through the existing projection with the position mark and context per tick; no new endpoint, no viewer-side control that can choose a token, no RPC from the viewer (the serve process imports nothing from `flytrade.pons.rpc`, tested). The two existing observer test sets stay green.

**14. Runs and their identities.** Replay: `d10-001`, branches `learning` (LEARN, from the **clean reference checkpoint**, the 09-08 hour then the 09-09 hour in strict chronological order, one brain carried through) and `frozen_reference` (FROZEN, same data, same seeds, clean checkpoint, digest unchanged — the mechanical control, not a scientific comparison). Determinism: a second execution of `learning` must reproduce the first bit for bit (the D9(b) measurement, repeated once). Expected activity stated in advance: with 546 launches, 30-second ticks, a 15-minute lock-out and two one-hour windows, **at most 8 episodes per window, 16 in total**; fewer if the brain waits, and zero is an admissible result that is reported as such. Live: `d10-live-001`, LEARN, starting from `d10-001/learning`'s final checkpoint (declared here, before the run) so continuity replay → live is exercised, with the finite limits of addendum 15.

**15. Live exercise (stage E), finite.** Preconditions: `eth_chainId` = 4663 on the configured endpoint; the ledger below the caps; the observer running. Limits: **60 minutes wall clock or 3 000 requests**, whichever first, then a clean stop with the cursor, ledger, journal and checkpoint persisted (`stop` is a file flag and SIGTERM, both tested). Health: `/api/summary` for a live run reports `data: LIVE`, cursor block, head block, lag in blocks and seconds, requests used and remaining, last error code, and `fresh: false` whenever the last confirmed block is older than 120 s — a connection is not fresh data. Start / stop / status are three documented commands. If the endpoint refuses (`RPC_ERROR_-32000` was seen by the donor on 2026-09-09 with an unconfirmed cause), the run stops on the first error with no retry and the report names the link as blocked, with the error code and request count; the replay evidence stands on its own. **The live launch rate is measured** (factory `TokenLaunched` per hour over the backfill) and reported next to the documentation's "whitelisted only" statement; zero admitted candidates in an hour is a valid result.

**16. Tests, gate, evidence.** Baseline `593 passed, 2 xfailed` preserved; the thirteen bullet groups of amendment section 13 map to named tests under `tests/d10/` (the reuse table lists which). Scripted RPC and scripted decoder fixtures are labelled as such in their module docstrings; no fixture number is ever reported as an observation. `.venv/bin/python -m pytest tests/` twice at closure. The report (`experiments/d10/runs/<run>/results.md`) separates the four conclusions of section 13 and never merges them; conclusion 4 for this wave is expected to read "not tested — no predictive evaluation was designed for D10".

**17. Isolation and secrets.** The donor is never modified, its PostgreSQL never started or stopped, nothing under `~/Documentos/PONS` executed; only JSON, `.sol` evidence and fixtures are copied, each with sha256 and origin path in `REUSE.md`. No `.env` is copied or read except the one key, by name, at runtime. A test greps every artifact the wave produces for the endpoint host and the key material and fails on a hit.

**18. Deviations.** Declared in the HANDOFF block with the D9(b) wording, never absorbed. A blocked link (stage E most likely) is named with the exact error; the independent stages are still completed in full.

**19. Cost, argued before dispatch.** Requests: ≤ 20 verification + ≤ 3 000 live + settlement confirmations (2 per episode) against a 10 000 cap; replay 0. Compute: replay of two hours at 30-second ticks is ≈ 240 rounds × ≈ 1.2 s (the D9(b) benchmark for 6 candidates at k = 8) ≈ 5 minutes per branch. Agent time is the real cost and the owner lifted its ceiling for this session; the wave is split into three sequential agent dispatches (A+B+dataset import, C+D, E) so each report can be reviewed before the next starts.

### Reviewer decisions after dispatch 1 (Fable, 2026-09-12) — amend the addenda above where they conflict

Dispatch 1 (commits `596ce4e`…`cbbd18d`) verified chain 4663, both factory code hashes, `safe` support, a median block interval of **0.101 s** (`confirm_depth` = 594 blocks), a live launch rate of **≈ 523 `TokenLaunched` per hour** on the v2 factory, and imported the donor's 1,136-launch census (546 native ETH) as `data/pons/d10-replay-v1`, with the curve port reproducing 3/3 fixture rows, 546/546 calibrations and 13,704/13,704 settled trades. Two findings force amendments:

1. **The donor dataset covers only the first ≈ 62 s of each token**, so a 15-minute horizon admits nothing on it. Addendum 8 is amended: `d10-replay-v1` stays as validation evidence and probe material; the replay run of addendum 14 uses a **new bounded genuine collection, `data/pons/d10-backfill-v1`**, made by the same collector through bounded HTTP backfill: window = the **135 minutes of blocks ending at the `safe` block recorded by verification (60,801,426)**, chosen by that rule and by nothing observed inside it; launches admitted from the first 120 minutes, the last 15 minutes are the settlement tail; native-ETH v2 launches only; factory and tracked-curve `eth_getLogs` in chunks (1,000 blocks for the factory, ≤ 500 for curves, halved on a provider range/size error down to 25 and then stopped — a range error is `RPC_RANGE_TOO_LARGE`, distinct from a quota halt, and the quota regex is narrowed so a range message never halts the run); initial curve state read lazily by `eth_call` at the launch block only for tokens that reach admission (or derived from the launch config if dispatch 2 proves, on all 546 calibrations, that the initial state is a function of `launchConfigId` and `graduationThreshold` plus one creator-tax read); **cap 3,000 units for this collection**, cursor and ledger persisted, the dataset ends where the cap ends if it is reached. Expected activity for the replay is restated: **≤ 9 episodes** for the whole window; zero remains admissible.
2. **Block headers, not logs, dominate cost** (a 30-s tick spans ≈ 300 blocks). Addenda 6 and 7 are amended: headers are fetched on a **sparse grid of one per 100 blocks (≈ 10 s)** plus the `latest` header per tick; timestamps of blocks between grid points are **linearly interpolated** and every timestamp derived this way is stored with a `interpolated: true` flag and a declared precision of ± the grid interval; hash anchoring holds at grid points and through the `blockHash` carried by every log; the confirmation check of addendum 7 re-reads the grid header nearest below the block in question. Cadence, latency and horizon stay in seconds of chain time under this mapping. Live budget per tick becomes ≈ 3 + 3 grid headers + lazy state reads + 2 per settlement; addendum 15's 3,000-request cap is kept and now buys the full 60 minutes.
3. **Feature windows are clipped to the launch, not zeroed.** Addendum 9 is amended: `ret_w = log(p_cutoff / p_at(max(cutoff − w, launch)))` and `drawdown_5m` uses the maximum since `max(cutoff − 5 min, launch)`; a token younger than the window measures since its launch. Scales are set from the statistics of the tokens launched in the **first 60 minutes** of the backfill window, at 30-second grid points, on the median and 90th percentile of |x|, before any outcome, PnL or post-cutoff return is computed; `age` scale is declared as 600 s (a constant, not fitted). `PLAN.md` and `config.json` are committed alone after the scales are set and before the run.
4. Accepted from dispatch 1's declarations, without change: `data/MANIFEST.md` is the one file under `data/` that the wave edits; `clear_halt` exists, is manual, was used once and is audited in the ledger; the allowlist is six methods; `pycryptodome==3.23.0` in the `chain` optional group; `eth_getCode` by tag; the tracked-curve query includes curves revealed in the same range.

## D11 — recent-activity admission, sensory context and reinforcement scale — canonical amendment (owner, 2026-09-12, original in English)

D11 APPROVED — RECENT-ACTIVITY ADMISSION, SENSORY CONTEXT
AND REINFORCEMENT SCALE

Read the session log, docs/SPEC.md and:
experiments/d10/closure_complement.md

Reported starting point: 235639a.
Verify the actual full commit and working-tree state.

Use the local artifacts as the source of truth where the
pasted report is truncated.

OBJECTIVE

Correct the preparation of the Pons experience:
- admit recently traded candidates;
- preserve meaningful activity differences in sensory input;
- reduce loss of outcome-magnitude information from clipping.

This wave includes design, implementation and focused tests.
It does not include a new market-neural experiment.

No new RPC collection, live exercise, parameter search,
visual redesign or real-money execution.

1. PRESERVE D10 AND THE WORKING CORE

Keep all D10 logs, results, checkpoints and configurations.

Preserve:
- k=8, gain and neural presentation window;
- decoder populations, signs, baseline and thresholds;
- biological plasticity mechanism and learning rate;
- normalized episode-specific credit assignment;
- exact curve quoting, costs and accounting;
- fixed 15-minute horizon and position sizing;
- collector budgets, recovery and observer contracts;
- upstream and its audit.

Do not return to IBM/Alpaca.
Do not add another sensory modality or market route here.

The D10 outcome was not a profitable-learning demonstration.
Do not rewrite it after correcting its environment.

2. RECONCILE THE DIAGNOSTIC FIRST

Using existing artifacts only, identify:
- the 17 reported entries by run, branch and episode;
- the 15 entries lacking recent activity;
- the 8 actual learning updates;
- which comparison branches produced no learning.

Do not combine duplicated replays or reference branches into
an apparent larger number of independent experiences.

Confirm candidate stimulus equality from deterministic encoded
inputs before Poisson sampling, not only from zero-valued
display fields.

Do not call a token permanently dead because no trades were
observed before the dataset ended.

3. ADMISSION V2 — RECENT ACTIVITY

For new entries, add these fixed engineering defaults:

recent_window_seconds = 120
minimum_valid_trades_in_window = 2
maximum_seconds_since_last_trade = 60

Evaluate against the canonical market-information cutoff.
Use only successfully decoded, valid nonzero trade events
available at that cutoff.

Count both buys and sells.
Creation, liquidity configuration and duplicate logs are not
additional trades.

Retain existing supported-route, data-completeness and
execution-availability requirements.

Do not rank admission by:
future returns, eventual survival, ticker, direction of recent
return, promoter identity or desired trading outcome.

These are recent-activity filters, not an organic-flow,
anti-manipulation or profitability classifier.

Make admission reversible:
an inactive candidate may return after new qualifying activity.

Keep the existing non-profitability-based rotation.
Use fewer than six candidates when fewer qualify.

If none qualify, emit NO_ELIGIBLE_CANDIDATES.
Never relax criteria automatically to force a decision.

Distinguish:
- inactive candidate;
- insufficient history;
- missing/lagging collector data;
- unsupported route;
- neural NO_RESPONSE.

A collector outage cannot be interpreted as every token
becoming inactive.

Admission controls NEW entries only.
Continue observing and settling existing positions even if
their token no longer satisfies admission.

4. ENCODER V2 — PRESERVE CONTEXT

Restore seconds_since_last_trade as an actual sensory input.

Document its causal calculation, normalization, rate mapping
and populations. Do not feed it directly to reward or output
neurons.

Preserve or explicitly represent:
- recent trade count;
- gross traded volume, not merely net signed flow;
- direction/imbalance where already available;
- recency of the last trade;
- data validity and observation coverage.

Distinguish:
A. No trades in the observed interval.
B. Multiple trades with almost no net price change.
C. Balanced buys and sells with meaningful gross volume.
D. Missing or incomplete observations.

Do not turn missing data into zero.
Do not add random jitter, ticker-dependent stimulation or
invented activity to make candidates appear different.

Identical measured contexts are allowed to encode identically.
The requirement is to preserve the declared distinctions,
not manufacture uniqueness for every token.

Use the existing verified olfactory pathway.
Do not retune gain or decoder to compensate for encoding errors.

Create a new encoder version and input-schema hash.
Reject silent loading of incompatible checkpoint metadata.

5. REINFORCEMENT SCALE — ONE FIXED RULE

Inspect table B.4 and the existing reward implementation.

Calibration set:
the distinct, confirmed D10 LEARN outcomes that actually
generated the reported learning updates.

Exclude:
- duplicated reruns;
- frozen-reference outcomes;
- unresolved positions;
- estimated or unavailable settlements.

Reconstruct each net return from canonical accounting in its
declared denomination. Keep all costs included.

Use this engineering calibration rule:

q = 90th percentile of abs(net_return)
    over the calibration set, with linear interpolation.

new_full_scale = max(old_full_scale, 2 * q)

Preserve the existing signed normalization/clipping mechanism,
neutral treatment, learning rate and eligibility rules.
Replace only its full-scale parameter.

Use the same scale for positive and negative outcomes.
No subtracting average losses, refunding costs through reward,
or converting a net loss into positive reinforcement.

Register the rule before computing the new scale.

Record:
- included outcome identities;
- sample count;
- q and resulting full-scale value;
- old and proposed reinforcement for each outcome;
- clipping counts.

This small, selected D10 sample is a coarse engineering
reference, not an estimate of the whole memecoin market.

Do not tune the multiplier, quantile or scale after observing
BUY frequency or a new run's performance.

Freeze the scale for the next experiment version.
No rolling recalibration during operation.

Do not apply the proposed rewards to old checkpoints.

6. LOCAL EVIDENCE WITHOUT A NEW NEURAL RUN

On existing recorded decision cutoffs, report:
- candidates admitted by v1 and v2;
- exclusion reasons;
- rounds with zero eligible candidates;
- available candidate counts and rotation coverage;
- deterministic sensory collisions before and after;
- examples showing the declared activity distinctions.

All eligibility calculations must stop at the historical cutoff.
Do not inspect subsequent trades to decide admission.

This is a retrospective admission/encoder diagnostic.
It does not calculate the trades the corrected brain would
have chosen and is not a corrected PnL backtest.

Do not loosen the admission rule because it leaves few candidates.
Report that limitation.

7. TESTS

Add focused tests for:
- recency and recent-count boundaries;
- buys and sells counted symmetrically;
- no future-event admission;
- duplicate/reverted events excluded;
- reversible readmission;
- no stale-candidate fallback;
- collector gaps separated from genuine inactivity;
- open positions preserved after admission expiry;
- metadata and iteration-order invariance;
- active-flat versus inactive sensory inputs;
- zero versus missing data;
- no manufactured sensory diversity;
- monotonic, sign-symmetric reward magnitudes;
- neutral and extreme outcomes;
- one normalized learning event per outcome;
- incompatible encoder/checkpoint metadata rejected.

Unit tests and the ordinary regression gate are permitted.
Do not launch new historical or live market-neural runs.

8. HANDOFF AND NEXT-RUN PREPARATION

Prepare a versioned D11 configuration, not a running service.

The next behavioral validation should start from a declared
clean reference checkpoint under a NEW experiment identity.

That is an explicit new encoder/environment experiment,
not a silent erasure of D10's losses or learned state.

Keep the original D10 identity, learned checkpoints and pending
position available for recovery under their original policy.
Do not cancel, close or migrate that position merely because
the observation exercise ended.

A combined correction cannot identify which individual change
caused a later behavioral difference. Report it as an integrated
environment repair, not isolated proof about any one component.

Deliver:
- concise design and exact configuration;
- code and focused tests;
- retrospective admission/encoding report;
- reward-calibration artifact;
- regression results twice at closure;
- commits, clean-tree status and updated HANDOFF.

No new visual work.
No profitability requirement.
Stop before the next collection or neural exercise.

### Owner rationale recorded with the amendment (2026-09-12, from Portuguese)

The D10 closure showed the concrete defect of that version: the fly was receiving candidates with identical "smells" — 15 of 17 entries on tokens without trades for 8.5 to 58 minutes, every other measurement zero, and the data preparation not preserving the relevant difference — so it was tie-breaking noisy responses to one stimulus, not distinguishing markets. That changes the reading of the losses: it does not show the brain would choose well with better inputs, but it shows those entries were not a useful comparison. The integration itself is settled (collection, curve, paper execution, records, learning, recovery), the suspected double charge of impact was not confirmed, and the clipping made losses of different sizes arrive as the same punishment. The owner's decision is D11: correct admission, sensory representation and reinforcement scale in one local wave; keep the 15 minutes; do not change the brain, the holding time and the interface at the same time. The admission numbers are an explicit initial engineering choice, not a discovery of which tokens profit; if none qualify the fly has no candidates, and old tokens are not fetched to fill six slots. The encoder must distinguish activity from price movement and must not turn missing data into a legitimate zero; time since the last trade must reach the sensory channels. The reinforcement scale changes, not the accounting; the value is computed by the deterministic rule above from the recorded outcomes, registered and frozen, never searched. On the observer: the page opened at close shows the record of an already finished hour, not a fly operating now, and that must stay visible in the interface. The next step is not "try until it wins"; it is to stop presenting different markets as the same smell, let the fly observe recent activity, preserve differences between consequences, and then see what it does.

### Fable addenda (reviewer, 2026-09-12) — binding for the D11 wave

**1. Identity and layout.** Wave D11; experiment identity `d11` (`experiments/d11/`: `PLAN.md`, `config.json`, `reward_calibration.json`, `retrospective.md`, the diagnostic scripts); code as new versions beside the old ones in `flytrade/pons/` (`admission_v2`, `pons_context_v2`, `pons_encoder_v2`), the v1 objects untouched so D10's logs, tests and the determinism check keep reproducing; tests in `tests/d11/`. Nothing under `experiments/d10/` changes except nothing; `git diff --stat 235639a -- experiments/d10 data/market upstream tests/upstream_audit experiments/d7 experiments/d8 experiments/d9b experiments/historical/runs` must be empty at close. The D10 pending position (`d10-live-001`, episode 72000315) stays exactly as recorded.

**2. Register-then-compute, twice.** (i) `experiments/d11/PLAN.md` + `config.json` are committed alone **before** the reward calibration is computed and before the retrospective is run; they contain the admission constants (120 s / 2 trades / 60 s), the v2 feature list with every scale rule stated (not the fitted numbers for the two new fitted ones — see 4), the calibration rule verbatim (q = linear-interpolated 90th percentile of |net_return| over the calibration set; `new_full_scale = max(old_full_scale, 2 q)`), the calibration set's selection rule, and the declared next-run identity `d11-001` from the clean reference checkpoint `ba95b60503d6…`. (ii) The computed scale and the two fitted feature scales are then written to `reward_calibration.json` and `feature_scales_v2.json` and the config is amended by **one commit that adds those numbers and nothing else**, cited in PLAN.md as the calibration commit. Nothing in either file is changed after that.

**3. Admission v2, exactly the owner's rule plus what v1 already required.** Admitted for a **new entry** iff: every `admission_v1` condition except its "≥ 3 trades ever" (route `pons-v2`, native ETH, curve open, reconstructed state valid, the 0.01 ETH buy does not exhaust the curve, age ≥ 60 s, coverage in replay) **and** at the cutoff: ≥ 2 valid trade events (`CurveBuy` or `CurveSell` with nonzero quote and token amounts, deduplicated by log id, orphaned/removed excluded, snipe-exemption and administrative events not counted) inside `(cutoff − 120 s, cutoff]`, and the last such trade ≤ 60 s before the cutoff. Reason codes, distinct from each other and from neural statuses: `INACTIVE` (fails the recency rule with a complete tape), `INSUFFICIENT_HISTORY` (age < 60 s or tape too short), `COLLECTOR_LAG` (the observation's confirmed/fast block is older than 2 ticks = 60 s behind the cutoff clock, replay: never), `QUOTE_UNSUPPORTED`, `ROUTE_COMPLETED`, `STATE_INVALID`, `COVERAGE`, `CURVE_EXHAUSTED`; the round's record carries per-token reasons. Reversible by construction (evaluated fresh every tick). Rotation unchanged; < 6 allowed; none → the round is `NO_ELIGIBLE_CANDIDATES` and no presentation happens. Held positions are observed, marked and settled regardless of admission. `COLLECTOR_LAG` on the whole tracked set marks the round `DATA_LAG`, never a sea of `INACTIVE`.

**4. Context v2 and encoder v2.** Features, in this order, all causal at the cutoff and clipped to launch as in D10: `age` (scale 600 s, unchanged), **`since_last_trade`** (seconds since the last valid trade; scale **60 s = the admission bound**, a declared constant, so an admitted token spans (0, 0.76] and a held token that goes quiet keeps rising toward 1), `ret_30s`, `ret_2m`, `ret_5m`, `flow_imb_2m` (scales as D10's `feature_scales_v2.json`), **`trade_count_2m`** (valid trades in the window, replaces `trade_rate_2m`; scale fitted: p90 of |x| over the 30-second grid points of tokens launched in the first 60 minutes of `d10-backfill-v1` **that admission v2 admits at that point**, no outcome anywhere), **`gross_volume_2m`** (sum of quote in and quote out of valid trades in the window, in ETH; scale fitted the same way), `rv_2m`, `drawdown_5m` (scales as D10). Ten features → 20 channels of the 31 candidate glomeruli; the channel map is written to config. The four owner distinctions are then measurable in the deterministic rate vector: **A** (no trades) → `trade_count_2m = gross_volume_2m = 0`, `since_last_trade` large; **B** (many trades, flat price) → count and volume high, returns ≈ 0, rv small; **C** (balanced with volume) → volume high, `flow_imb_2m ≈ 0`; **D** (missing/incomplete) → **not presented**, status `INSUFFICIENT_TAPE` or `COLLECTOR_LAG`, never a zero vector. The encoder carries `encoder_version = "pons_encoder_v2"` and `input_schema_sha256` = sha256 of the ordered feature names, scales and channel map; the checkpoint metadata gains both; **loading a checkpoint whose metadata carries a different schema hash for continued learning raises** unless the run is declared `from_clean_reference` and the checkpoint is the clean reference (which predates the field and is the only one allowed to lack it). Sign-fixed features keep the two-channel rule (declared, as D10). "Identical measured contexts encode identically" stays true; the test for "no manufactured diversity" asserts that two tokens with equal raw vectors and different addresses produce equal rate vectors.

**5. Reinforcement scale.** The calibration set is the **8** LEARNING records that exist: `d10-001/learning` episodes 1–7 and `d10-live-001` episode 1 (the determinism re-run is the same events, not new ones; `frozen_reference`'s 8 `SETTLED_FROZEN` produced no update and are excluded; the pending live position is excluded). `net_return = net_pnl / notional` with notional 0.01 ETH, both read back from the OUTCOME records and re-derived from the leg integers in `closure_complement.md` (they must agree). `reinforce_full_scale` becomes a **per-experiment config parameter** carried in the D11 config and read by the Pons loop; the IBM default 0.01 and every D5–D10 code path stay byte-identical (tested: the historical loop's reinforcement on a fixed outcome is unchanged). The artifact records the eight identities, |r| each, q, the new scale, old and proposed `amount` per outcome, and clipping counts under both. No other constant of the rule moves.

**6. Retrospective diagnostic (owner section 6), from the recorded cutoffs only.** Inputs: the ROUND records of `d10-001/learning` (272 ticks) and `d10-live-001` (111 ticks), plus the datasets/chain stores those runs read. For every tick: tokens admitted by v1 (as recorded) and by v2 (recomputed at that cutoff, with the tape truncated at the cutoff), reasons for exclusion, ticks with zero eligible, candidate counts, how many ticks would have presented < 6; **deterministic sensory collisions**: for each tick the number of presented candidates whose v1 rate vectors are equal (tolerance 1e-9 Hz) and the same for the v2 vectors on the v2-admitted set — before Poisson sampling, from the deterministic encoder output, not from display fields; the 17 entries re-identified by run/branch/episode with their v2 verdict (`INACTIVE` or admitted); worked examples for A/B/C/D drawn from real tokens with their rate vectors. Written to `experiments/d11/retrospective.md` with one line stating it is not a backtest and computes no trade the corrected brain would have made.

**7. Tests and gate.** The sixteen owner bullets map to named tests in `tests/d11/`; scripted fixtures labelled; baseline `848 passed, 2 xfailed` preserved; gate 2× at close. No historical or live neural run; no RPC call (test: the D11 scripts import nothing from `flytrade.pons.rpc`).

**8. Observer.** No visual work. The backend already exposes `status`, `stop_reason` and `worker_alive` for `d10-live-001`; the wave adds nothing there and the HANDOFF repeats, for the visual track, that a finished run must be labelled as a record, not a live fly.

**9. HANDOFF and stop.** One block "(k)" ≤ 25 lines: the reconciliation of section 2, the v2 rules, the schema hash, the calibration numbers, the retrospective's headline counts (collisions before/after, zero-eligible ticks, the 15/17), deviations declared, and the queue: `d11-001` (replay on `d10-backfill-v1` from the clean reference, then one live hour) as the next owner decision, with an evaluation designed before it. Stop there.

## D11-001 — preregistered Pons learning evaluation — canonical spec (owner, 2026-09-13, original in English)

D11-001 — PREREGISTERED PONS LEARNING EVALUATION

Run the first neural experiment using the accepted D11 environment repair.

Use:
- admission_v2;
- pons_context_v2;
- reinforcement full scale = 0.131;
- k=8;
- existing decoder;
- fixed 15-minute paper hold;
- one persistent learned brain;
- clean reference checkpoint.

Do not modify these parameters after observing results.

DATA

Use only d10-backfill-v1.

Order launches and observations chronologically.

Split by time, never randomly.

Use the earliest 70% of the usable chronological market window
as LEARNING and the final 30% as FROZEN EVALUATION.

Compute the split from timestamps only, before calculating
any trade outcomes or neural results.

Require every learning/evaluation episode and its full
15-minute settlement window to remain inside its own partition.

Events near the boundary that cannot settle entirely inside
their partition are ineligible.

Record the exact cutoff timestamp before running the brain.

LEARNING

Start from the clean reference checkpoint.

Run the normal D11 Pons loop chronologically.

Only actual neural BUY entries that settle generate reinforcement.

Carry one learned brain across tokens.

Record:
- eligible candidates;
- neural score/action;
- paper outcome;
- raw and normalized reinforcement;
- synapses affected;
- checkpoint digest after each update.

FROZEN EVALUATION

Create two branches over exactly the same later observations:

TRAINED:
final LEARNING checkpoint.

REFERENCE:
original clean checkpoint.

Disable learning and forgetting in both.

Use identical exogenous replicate seeds between branches,
independent of checkpoint digest.

Do not allow branch behavior to change which observations
are available for the primary neural comparison.

PRIMARY EVALUATION GRID

At every eligible candidate presentation in FROZEN, record
the continuous pre-threshold neural score for both branches.

Attach the actual fixed-15-minute net outcome available from
the recorded Pons market as an evaluator-only label.

This hypothetical label:
- does not create a trade;
- does not alter bankroll;
- does not produce reinforcement;
- uses the same quote/cost model as the paper executor.

Compare TRAINED vs REFERENCE on the same candidate/timestamp rows.

PRIMARY QUESTION

Does training improve ranking of later Pons contexts?

Report per temporal block and overall:
- AUC / pairwise ranking of neural score versus positive
  fixed-horizon outcome;
- trained minus reference difference;
- coverage and class balance.

Do not interpret AUC near 0.5 as proof that no signal exists.

SUPPRESSION CHECK

Report separately:
- BUY / SELL / WAIT / NO_RESPONSE frequencies;
- mean and distribution of continuous neural scores;
- fraction of candidates crossing the BUY threshold.

A lower BUY rate alone is not learning success.

REINFORCEMENT CHECK

For LEARNING report:
- number of updates;
- raw return magnitude;
- normalized reinforcement amount;
- clipping count at full scale;
- reward / punishment counts.

Explicitly compare the new scale behavior with D10's
7-of-8 saturation as historical context.

Do not change the scale because the new distribution looks
too weak or too strong.

CONTEXT CHECK

Report:
- candidates per round;
- rounds with zero eligible candidates;
- admission rejection reasons;
- deterministic sensory collisions;
- distribution of seconds_since_last_trade;
- recent trade counts and gross volume among admitted tokens.

Verify that the D10 failure mode — effectively indistinguishable
inactive candidates — is absent or quantify where it remains.

PAPER RESULTS

Also report actual paper:
- trades;
- gross result;
- costs;
- net result;
- holding durations;
- unresolved positions.

These are descriptive, not the primary learning metric.

INCONCLUSIVE CONDITIONS

Declare the learning evaluation INCONCLUSIVE rather than
stretching interpretation if any of these occurs:

- fewer than 20 completed LEARNING episodes;
- fewer than 100 paired FROZEN candidate labels;
- either positive or negative outcome class has fewer than 20
  labeled examples;
- paired neural coverage below 95%;
- material encoder saturation or invalid-state rate above 5%.

Do not loosen these thresholds after the run.

AFTER REPLAY

Only after the replay and frozen report are complete:

start a separate one-hour LIVE_PAPER exercise from the final
trained checkpoint using the same D11 configuration.

Do not continue learning from replay into live silently:
record the checkpoint hash explicitly.

Keep learning enabled during the live hour if that is the
declared d11-001 live branch.

Report replay and live results separately.

No parameter tuning between them.

No real-money execution.

DELIVERY

Provide:
- preregistration commit before neural execution;
- exact temporal split;
- replay LEARNING results;
- paired FROZEN results;
- suppression diagnostics;
- reinforcement diagnostics;
- context/admission diagnostics;
- one-hour live result;
- RPC usage;
- observer-compatible run;
- tests and clean tree;
- updated HANDOFF.

Do not declare predictive learning based on PnL alone.
Do not declare failure because the fly loses money.
Stop after d11-001.

### Owner rationale recorded with the spec (2026-09-13, Portuguese, verbatim)

Sim. Agora estamos num ponto bem mais limpo.

O backend da Pons já funciona. O que a D11 fez foi consertar o ambiente antes de culpar ou elogiar a mosca: agora ela só recebe candidatos vivos, os contextos não colapsam quase todos no mesmo "cheiro" e uma perda pequena não vira automaticamente punição máxima.

Mas tem um detalhe crucial:

essas correções ainda não foram dadas para a mosca.
A D11 foi só design + código + testes. Nenhuma nova experiência neural foi rodada.

Então o próximo passo correto é d11-001:

cérebro limpo;
Pons replay real;
admission_v2;
pons_context_v2;
escala de reward 0,131;
ela aprende numa parte cronologicamente anterior dos lançamentos;
congelamos o cérebro;
comparamos treinada vs. referência virgem em lançamentos posteriores;
só depois pegamos o checkpoint final e deixamos uma hora na Pons chegando ao vivo.
O que eu quero medir

Não quero repetir a cagada de olhar só "ganhou/perdeu".

A pergunta é:

Depois de aprender com memecoins anteriores, o cérebro reage de maneira diferente aos contextos posteriores de uma forma relacionada ao resultado?

E também queremos saber se corrigimos aquela patologia de:

toma sete porradas parecidas → para de comprar qualquer coisa.

Então eu pré-registraria quatro coisas:

discriminação: score neural maior para entradas que posteriormente dão melhor resultado;
supressão: BUY cai globalmente ou muda de acordo com contexto?;
reward: quantas atualizações entram fracas, médias e no teto com a escala nova;
atividade: quantos candidatos realmente diferentes ela recebe e quantos episódios ela completa.

PnL fica registrado, obviamente, mas não é o critério para dizer se o cérebro aprendeu.

E eu faria o corte por tempo de lançamento, nunca randomizando tokens. Tokens mais antigos ensinam; tokens posteriores fazem a prova. Isso evita ela ver irmãos temporais do mesmo regime nos dois lados.

Minha decisão

GO para d11-001.

E eu usaria este bloco curto antes do agente rodar qualquer número:

[the English block above]

Se isso der zero de novo, eu paro de ficar mexendo no cérebro atrás de alpha e vou 100% para espetáculo.

Mas se aparecer qualquer diferença real entre treinada e virgem nos tokens posteriores, mesmo que as duas percam dinheiro, aí ficou interessante pra caralho.   -  Temos um nó nitro local agora

### Owner decision on the data (2026-09-13, Portuguese, verbatim; line breaks restored, the answer arrived flattened through the question tool)

Context for the decision. The reviewer's feasibility check before dispatch: `d10-backfill-v1` spans 135.8 min (2026-09-12 01:37:36Z – 03:53:25Z, 8,149 s); the executor holds one paper position at a time (`max_open_positions: 1`), one entry per 30-s tick, fixed 900-s hold; a 70 % LEARNING partition is 95 min, the last entry that settles inside it is at minute 80, so the geometric ceiling is 5 to 6 completed learning episodes against the spec's floor of 20 — INCONCLUSIVE by construction. Three options were put to the owner: (1) a new 12-hour backfill through the local Nitro node with the executor untouched; (2) simultaneous paper positions on `d10-backfill-v1`; (3) lowering the floor before the run. The owner's answer:

Escolhe 1. Backfill de 12 horas pelo nó local.

É a opção certa porque mantém o experimento que acabamos de desenhar intacto: uma posição por vez, hold de 15 min, admission_v2, encoder_v2, reward 0,131. A única coisa que muda é a quantidade de mercado disponível para a mosca aprender.

As outras duas contaminam mais o teste. Posições simultâneas mudariam bastante a mecânica e o crédito de aprendizado; baixar o piso para cinco episódios faria a gente aceitar de antemão uma amostra que já sabemos ser fraca.

Com 12 h, os 70% de LEARNING dão cerca de 8,4 horas de mercado. Com uma posição por vez e 15 min de hold, o teto teórico vai para ~33 episódios; depois das bordas, WAIT, SELL, falta de candidatos etc., a estimativa de ~20–30 episódios reais é plausível. Aí o piso de 20 deixa de ser impossível por construção.

Eu responderia ao Claude assim:

Escolha 1.

D11-001 usará um NOVO backfill Pons de 12 horas contínuas,
d11-backfill-v1, coletado pelo nó Nitro local.

Preservar:
- max_open_positions = 1;
- hold = 15 min;
- k=8;
- admission_v2;
- pons_context_v2;
- reinforcement_full_scale = 0.131;
- decoder e cérebro atuais.

Não usar posições simultâneas.
Não reduzir o piso de 20 episódios.

O d10-backfill-v1 permanece imutável como baseline histórico.

Antes da coleta:

1. Localizar e verificar o endpoint Nitro local.
   Não assumir que porta 4663 significa chain 4663:
   confirmar eth_chainId e bloco atual.
2. Se mais de um endpoint local existir, usar apenas aquele
   cuja chain e comportamento forem verificados.
3. Registrar um orçamento específico para LOOPBACK/local,
   separado do budget Chainstack.
   Não consumir Chainstack silenciosamente como fallback.
4. Primeiro fazer um probe pequeno para verificar se o nó
   suporta os métodos/ranges históricos necessários.
5. Se alguma leitura histórica exigir archive state que o nó
   local não fornece, medir exatamente quais chamadas precisam
   de fallback antes de autorizar qualquer uso de Chainstack.
   Não fazer fallback automático.
6. Definir o intervalo exato de 12 horas por timestamps/blocos
   ANTES de calcular outcomes ou respostas neurais.
7. Coletar e persistir uma vez; replay neural posterior deve
   usar o dataset local, não refazer RPC.

Depois da coleta, calcular o split 70/30 apenas por tempo e
registrar o cutoff antes da primeira rodada neural.

Então executar o spec D11-001 já aprovado.

Se mesmo com 12 horas houver menos de 20 episódios LEARNING,
o resultado é INCONCLUSIVE conforme pré-registrado.

Não aumentar concorrência, mudar hold, baixar o piso ou
estender novamente a janela depois de ver o resultado.

Relatar separadamente:
- requests ao nó local;
- qualquer request Chainstack;
- lançamentos/eventos coletados;
- candidatos admitidos;
- episódios máximos possíveis pela geometria temporal;
- episódios realmente produzidos pelo cérebro.

E tem um motivo adicional para eu gostar dessa opção: Pons tem muito mais amostras disponíveis que IBM. Se queremos saber se essa mosca aprende alguma coisa, faz muito mais sentido dar a ela algumas dezenas de experiências honestas do que redesenhar o sistema para espremer seis exemplos de duas horas.

Pode marcar 1.

The local node's address was left to the agent to discover ("Agente descobre sozinho").

### Fable addenda (reviewer, 2026-09-13) — binding for the d11-001 wave

Where the owner's spec says `d10-backfill-v1`, the owner's decision above replaces it with `d11-backfill-v1`; everything else in the spec stands. These addenda add definitions the spec leaves open, using facts read from the code on 2026-09-13 (file pointers in the wave's PLAN.md).

**1. Identity, layout, and what does not move.** Run identity `d11-001` as already registered in `experiments/d11/config.json` (clean reference `ba95b60503d6…`, `pons_encoder_v2` with `input_schema_sha256` `3bf4f34c334a47cc960ad2619e091c4978f24d3eab0add63bb5c0a9501ff4615`, `admission_v2`, `reinforcement.new_full_scale` = 0.131032424). New code lives under `experiments/d11/` (`run.py` modelled on `experiments/d10/run.py`, the collection entry point, `grid.py`, `evaluate.py`) with outputs under `experiments/d11/runs/d11-001/{learning,frozen_trained,frozen_reference,grid,live}/`; the dataset under `data/pons/d11-backfill-v1/` in the D10 store layout (`events.jsonl`, `headers.jsonl`, `initial_states.json`, `MANIFEST.json`), and `initial_states.json` is mandatory because the offline tracker needs it for exact reconstruction. Fixed for the whole wave: `max_open_positions` 1, `horizon_seconds` 900, `cadence_seconds` 30, `max_candidates_per_round` 6, readout `k` = 8 replicates under `comparison_v1` with `keyed_to_learned_state: false`, the k = 8 decoder (θ = 0.9117185769796697 Hz), `paper_size_wei` 10^16, the D10 gas constants, latency 2 s. The owner's "k=8" is the readout replicate count; candidates per round stay 6. The Pons loop never calls forgetting (`mb.forget()` is unreachable from it), so "disable learning and forgetting" is satisfied by `FROZEN` mode; a test asserts the frozen branches' digests are unchanged at the end.

**2. Register-then-compute, three steps, and the hard stops.** (i) This spec commit. (ii) `PLAN.md` (one d11-001 section) plus the run configuration, alone, before any request to any node: the window rule (6), the loopback budget (4), the split rule (6), the grid and label definitions (7–8), the statistics plan with its bootstrap seed and the three temporal blocks (9), the inconclusive conditions verbatim, the saturation definition (11). (iii) After collection and split, numbers only: window blocks and timestamps, cutoff T, tick counts per partition, the geometric ceiling, grid row count and label class balance. The brain runs only after (iii). Hard stops, each ending the wave with a report and no neural run: no verified local node; any historical call that needs state the node does not hold (5); a pre-computable inconclusive condition already failed by construction (fewer than 100 settled grid labels, fewer than 20 in either class, or a geometric ceiling under 20). Nothing is re-chosen after a stop; the owner decides.

**3. The local node: discovery and verification.** Probe `127.0.0.1` on 8547 then 8545 with `eth_chainId`; a candidate is verified only if it returns 4663 and the timestamp of its `latest` block is within 300 s of wall clock. Use the first verified in that order; report every port probed and what it answered. The endpoint is committed as `experiments/d11/local_node.env` (`LOCAL_NITRO_RPC_HTTP=http://127.0.0.1:<port>`; a loopback URL is not a secret) and passed through the existing `--env-file/--env-key` path; the stockroom `.env` is neither read nor written in this wave. Capability probe, ≤ 40 requests, all ledgered: `eth_blockNumber`; `eth_getBlockByNumber` at head and at the block about 12 h back (bounded binary search on block timestamps); one `eth_getLogs` over one collector-sized chunk at the old end of the window; and every kind of historical `eth_call` the D10 backfill made (identified from `flytrade/pons/collector.py` and the D10 MANIFEST per-method block), executed at an old block. Any failure or state error → the list of (5) and stop.

**4. Loopback budget, separate.** `flytrade/pons/budget.py` classifies the endpoint by host: loopback (`127.0.0.1`, `localhost`, `::1`) gets its own ledger file (`experiments/d11/rpc_ledger_local.json`) and its own caps, registered in (ii) as three times the projected request count of the 12-h collection (projected from the collector's chunking and the D10 MANIFEST per-method counts scaled by block count; state the projection). The Chainstack caps, ledger and accounting are unchanged. During this wave a non-loopback request is refused by the budget layer unless `--allow-remote` is passed, and the agent never passes it. Tests: host classification, cap independence, refusal without the flag.

**5. No silent fallback.** If a call needs state the local node does not hold, the wave stops with the exact list (method, block, purpose, count) and its Chainstack cost in units; Chainstack is used only after the owner authorises that list. The final report separates loopback requests from any remote request, per the owner's list.

**6. Window and split.** Window: 12 contiguous hours ending at the confirmed head at probe time (confirmation depth as the collector defines it); `end_block` = that block; `start_block` = the smallest block with timestamp ≥ `end_ts − 43,200`. The window must not overlap `d10-backfill-v1` (2026-09-12 01:37:36Z – 03:53:25Z); if it would, move the end earlier until it does not. MANIFEST: `admission_minutes` 705, `settlement_tail_minutes` 15, blocks, timestamps, endpoint class and port, per-method request counts, sha256 of each file. Collected once; every later step reads the store, and a test parses `run.py`, `grid.py` and `evaluate.py` for network verbs as D11 did. Split: t0 = timestamp(`start_block`), t1 = timestamp(`end_block`), T = t0 + floor(0.7 · (t1 − t0)) snapped down to the 30-s tick grid anchored at t0, recorded in (iii) before any outcome or neural number. LEARNING ticks: cutoff ≤ T; an entry is allowed only if cutoff + 2 + 900 ≤ T; ticks in (T − 902, T] observe and settle, never enter; an assertion fails the run if a learning position is open at T. FROZEN ticks: T ≤ cutoff and cutoff + 902 ≤ t1. Three temporal blocks of equal duration over the FROZEN grid span. Geometric ceiling: the number of non-overlapping 932-s slots (902 s plus one tick) between the first LEARNING tick with at least one v2-eligible candidate and T − 902.

**7. The primary grid is a market-only scoring pass, not the loop.** Presentation in the loop depends on run state — while a position is held only the held token is presented, and the round-robin rotation advances with evaluated rounds — so two frozen loop branches cannot share rows. The grid is therefore: for every FROZEN tick, `admission_v2` on the tape reconstructed from the store alone (the `retrospective.py` tracker, exact with `initial_states.json`) → all eligible candidates (no cap of 6, no rotation, no hold mode; a superset of anything the loop could present) → each scored by both frozen brains with the standard readout (k = 8 replicates, `comparison_v1` seeds from `observation_id`/`stable_id`/replicate, already independent of the checkpoint digest; a test asserts `keyed_to_learned_state` is false on this config). Rows keyed by (cutoff_ts, stable_id), identical across branches by construction; per row and branch: valence, raw valence, readout status, decoded action at the k = 8 thresholds, checkpoint digest. Coverage = rows VALID in both branches / rows. The frozen brains are loaded read-only, digests verified before and after the pass. No execution, bankroll, reinforcement or checkpoint write happens in the grid.

**8. The evaluator-only label.** Per grid row: a hypothetical buy of 10^16 wei at cutoff + 2 s through `PonsPaperExecution.plan_buy` on a fresh execution object, hold 900 s, `plan_sell` on the tape advanced by the recorded external events with the hypothetical position's own delta carried exactly as the loop's settlement path does; net = quote_out − spent − gas_buy − gas_sell − approval with the D10 constants; positive iff net > 0. `Unresolved` (route transition) or `QuoteError` (exhausted curve) → label UNRESOLVED, excluded from AUC and counted. Known-answer test written before the grid runs: the label function at the 16 settled D10 entries, at their recorded cutoffs, reproduces each recorded net to the wei. The label never touches bankroll, ledger or reinforcement.

**9. Statistics, fixed in (ii).** Primary: ΔAUC = AUC(TRAINED) − AUC(REFERENCE) over rows VALID in both branches with a settled label; AUC = Mann–Whitney with ties counted ½. Uncertainty: paired cluster bootstrap by `stable_id` (a token's rows move together), 10,000 resamples, seed 20260913, percentile 95 % interval, overall and per block. Wording follows the owner's rule: an interval that includes 0 is reported as "compatible with sampling variation"; one that does not is reported with its bounds; no "significant", no "proves", no rate asserted as measured; AUC near 0.5 is not evidence of no signal. Secondary, descriptive: Spearman(score, net) per branch and their difference; the distribution of the per-row score difference TRAINED − REFERENCE. Suppression on the grid: BUY-crossing rate (V > θ) per branch, overall, per block and by later outcome class; the pre-registered reading is the between-class difference of the trained-minus-reference change with the same clustered interval — "global" if that interval includes 0, "contextual" if it excludes 0 with the larger drop in the negative class; nothing else is said in words. Known-answer tests: AUC 1, 0 and ½ on perfect, reversed and constant toy data; ties; identical branches → ΔAUC exactly 0; a one-cluster bootstrap is degenerate.

**10. The runs, in order.** LEARNING: `experiments/d11/run.py` → REPLAY_PAPER on `d11-backfill-v1` from the clean reference under `from_clean_reference`, LEARNING mode, the partition rule of (6); a test asserts the applied `reinforce_full_scale` is 0.131032424 on this config and 0.01 on the D10 config. Records as D10 writes them (ROUND scores, DECISION, EXECUTION, OUTCOME, LEARNING, CHECKPOINT); each LEARNING record also carries raw net, normalised amount and a clipped flag (amount = 1.0), added additively if absent. Final checkpoint = TRAINED, digest in the summary and in the grid manifest. Then the grid (7–8). Then the two FROZEN loop branches, descriptive: TRAINED and REFERENCE replays over the FROZEN partition (market state at T rebuilt from t0 without the brain), paper trading as D10's `frozen_reference`, `SETTLED_FROZEN`; their PnL, action frequencies and holds are the FROZEN "paper results", not the primary comparison. Then the report. Then the live hour (12).

**11. Diagnostics and definitions.** Encoder saturation, offline from the logged normalised vectors: a channel is saturated when its normalised value sits at the clip bound; report the fraction of (row, channel) pairs saturated and the fraction of rows with at least one; the inconclusive condition reads > 5 % on the (row, channel) fraction or an INVALID_STATE rate > 5 % on the grid. Also: admission rejection reasons per tick; `since_last_trade`, `trade_count_2m`, `gross_volume_2m` among admitted; deterministic 1e-9 Hz collisions on grid rows per tick; candidates per tick; zero-eligible ticks. Reinforcement: count, raw magnitude, normalised amount, clipped count, reward and punishment counts, beside D10's 7 of 8 as historical context. Geometric ceiling and produced episodes side by side.

**12. Live hour.** Only after the replay report is written: LIVE_PAPER, 3,600 s, from the TRAINED checkpoint with learning ENABLED (the declared d11-001 live branch), `starts_from_digest` verified and recorded, against the local node under the loopback ledger, with the D10 chainId gate (4663) and freshness rule (120 s). If the node is not fresh at start the live hour is not started and that is reported, not worked around. Same configuration, no tuning, separate report. Observer: add a D11 root to `observer/serve.py` `ROOTS`, restart on 8793; a finished run is labelled a record of an hour that already ended, never a fly operating now.

**13. Untouchables, tests, gate, docs.** `git diff --stat <this spec commit> -- experiments/d10 data/pons/d10-backfill-v1 data/market upstream tests/upstream_audit experiments/d7 experiments/d8 experiments/d9b experiments/historical/runs` empty at close; the D10 configuration path stays byte-identical (existing tests). `tests/d11/` mapped to the owner's sections (DATA, LEARNING, FROZEN, GRID, PRIMARY, SUPPRESSION, REINFORCEMENT, CONTEXT, INCONCLUSIVE, AFTER REPLAY, DELIVERY) plus the budget and label tests above. Affected suites during work; the full gate twice at close only. HANDOFF block ≤ 25 lines; PLAN.md one section; no research document. Deviations declared, none absorbed. No real money, no signing, no funds. One Opus agent, sequential.

### Owner amendment after dispatch (2026-09-13, Portuguese, verbatim) — with the reviewer's reading, amends addenda 3 and 5

> Ele nao eh archive, tive q prunar, te vira com ele, porra analisa dos inferno, pega ate onde da.

**Reviewer's reading, binding, amends addenda 3 and 5. Everything else stands:
Chainstack stays forbidden, `--allow-remote` is never passed, and the stockroom
`.env` is never read.**

**1. No stop on missing historical state.** For each kind of historical
`eth_call` the D10 backfill made (identified from `flytrade/pons/collector.py`
and the D10 MANIFEST per-method block), classify and substitute:

* **(a) Immutable per token/curve** — constants, metadata, factory version,
  curve parameters: call at `latest` instead. Prove equivalence on
  `d10-backfill-v1`: call the same thing at `latest` for the D10 tokens and
  compare with the recorded `initial_states.json` values; every token the node
  answers for must match exactly. Record the substitution in `PLAN.md` and in
  the new MANIFEST (e.g. `state_source: latest_block_immutable`, with the
  verification counts).
* **(b) Mutable at the launch block** — reserves, supply, anything that moves
  with trades: reconstruct from events (`TokenLaunched` and what follows).
  Verify the reconstruction reproduces `d10-backfill-v1`'s
  `initial_states.json` exactly for the D10 tokens whose logs the node still
  serves; report the subset size if it is not all of them.
* **(c) Mutable and not reconstructible from events**: mark that token
  unsupported / `STATE_INVALID` in the store, count it, report the count.
  **Never guess a value.**

The verification is written as a test whose inputs are local files; the
live-node comparison of (a) is a ledgered probe, bounded and loopback only,
with its result recorded in the MANIFEST.

**2. Window.** Twelve hours is the target. If the pruned node does not serve
headers and logs contiguously that far back, take the **longest contiguous
window it does serve**, ending at the confirmed head, still not overlapping
`d10-backfill-v1`. The `getLogs` probe at the old end must return real logs (an
empty range is accepted only if adjacent ranges corroborate it); a pruned-data
error means shrink the window. Record the earliest available block and the
reason in the MANIFEST and in step (iii). **The geometric ceiling falls where
it falls.**

**3. Hard stops that remain.** No port verifies (chain id 4663 and a fresh
head); and, after step (iii), a geometric ceiling under 20, fewer than 100 grid
rows, or either label class under 20 — stop and report the numbers, and **do
not loosen** the owner's own floors.

**4. The report** lists every substituted call, its class (a/b/c), and how it
was verified, plus the actual window against the twelve-hour target.

## D12 — school mode: relative cohort reinforcement — canonical spec (owner, 2026-09-13, Portuguese, verbatim)

Agora apareceu uma coisa bem mais interessante que "perdeu dinheiro".

A mosca virgem ficou com AUC 0,588 e a treinada com 0,412. É praticamente um espelho. E durante o aprendizado ela recebeu 0 rewards e 15 punishments. Então o treinamento não ficou simplesmente aleatório: ele parece ter destruído/invertido um prior que o cérebro virgem já tinha. O veredito formal continua INCONCLUSIVE porque só houve 15 episódios, abaixo dos 20 pré-registrados, mas esse padrão merece atenção.

Para mim, isso encerra a dúvida de qual direção tomar: eu não mexeria em horizonte, encoder ou cérebro agora. Eu mudaria a maneira de ENSINAR.

O problema atual é que 15 minutos nesse ambiente produz resultado negativo em cerca de 90% dos candidatos. Com reward absoluto:

perdeu = punishment

a professora basicamente passa 90% da aula dando porrada. Não há contraste suficiente para ensinar qual memecoin é melhor. E ainda tivemos 11/15 atualizações batendo novamente no teto da escala 0,131.

Eu faria D12 como "escola da mosca"

Não exigiria mais que ela compre para poder aprender.

Durante replay histórico, mostramos a ela cada candidato elegível normalmente. Depois de 15 minutos, verificamos onde aquele token ficou em relação aos outros tokens que ela tinha disponível naquele mesmo momento.

Exemplo: ela viu seis memes:

A   +14%
B    +3%
C    -2%
D    -7%
E   -18%
F   -61%

A gente não diz previamente qual é bom.

Depois dos 15 minutos:

A recebe reward forte;
B reward menor;
C/D ficam perto de neutro;
E punishment;
F punishment forte.

Isso ensina:

"entre as coisas que você sentiu naquele momento, quais padrões precederam os melhores resultados?"

Em vez de:

"quase tudo dá prejuízo depois de taxas, então apanhe novamente."

Mesmo se os seis perderem dinheiro:

A   -3%
B   -8%
C  -15%
D  -28%
E  -50%
F  -82%

A foi a melhor escolha relativa. Para treinamento de seleção, isso contém informação.

Financeiramente continua aparecendo -3%. Não falsificamos lucro. Só separamos duas coisas:

resultado financeiro: −3%
sinal pedagógico: melhor entre 6 → reward relativo.

Isso é um objetivo diferente e deve ser chamado explicitamente de relative/cohort reinforcement, não de profit reward.

E eu iria além: usar todos os candidatos como aula

Essa é a parte que resolve o problema de amostra.

Hoje ela teve 15 experiências porque só aprende quando entra numa posição e existe uma única posição simultânea.

Na "escola", se num tick existem seis memecoins elegíveis, as seis podem virar experiências de condicionamento. Não são seis trades. São seis exemplos sensoriais com consequências observadas depois.

Isso é muito próximo do tipo de condicionamento que já demonstramos no mushroom body: estímulo → consequência → alteração da resposta.

Você consegue transformar algumas horas de Pons em centenas ou milhares de lições, em vez de quinze porradas.

Depois congelamos o cérebro e aí sim fazemos a prova:

tokens posteriores que ela nunca recebeu como aula.

Se a AUC do cérebro treinado subir em relação à virgem, temos uma coisa muito mais interessante.

Se continuar 0,5 ou pior, paramos de fantasiar que o aprendizado está funcionando e ficamos com o espetáculo.

Eu manteria 15 minutos

Justamente para não mudar duas coisas ao mesmo tempo.

D12 muda somente o objetivo pedagógico:

absolute profit reinforcement → relative cohort reinforcement.

Admission v2, encoder v2, k=8, cérebro, decoder e horizonte de 15 minutos ficam iguais.

E tem um detalhe fascinante para investigar antes da nova run: eu pediria uma conta barata sobre os scores já existentes para saber se o cérebro treinado virou aproximadamente o negativo do cérebro virgem. O 0,588 → 0,412 é quase exatamente AUC → 1 − AUC. Isso pode revelar mecanicamente o que quinze punishments fizeram.

Sobre o repo PONS

Não considero livre ainda. O próprio relatório diz que havia outra sessão modificando o repositório, que a árvore ficou suja com sete arquivos externos ao agente e que ele corretamente decidiu não despachar mais trabalho ali.

Então a ordem é:

confirmar que a outra sessão terminou → git status limpo ou mudanças identificadas/commitadas → só depois mexer no PONS.

E eu não colocaria ainda os dados de wallets/snipers dentro do cérebro. Essa trilha parece promissora — inclusive encontraram recorrência forte de snipers de bloco zero — mas se adicionarmos isso junto com o D12, mudamos novamente o que a mosca enxerga e não saberemos o que causou a diferença.

Minha escolha, portanto, é: D12 = treinar a mosca para escolher relativamente entre memes, em "school mode", usando muito mais experiências; depois prova congelada em tokens posteriores. Isso, para mim, é a próxima tentativa que vale compute.

### Fable addenda (reviewer, 2026-09-13) — binding for the d12-001 wave

The owner changes one thing: the teacher. These addenda define the teacher precisely and keep everything else the same object as in `d11-001`, so that any difference is attributable to the teaching rule alone.

**1. Identity, data, and what does not move.** Run identity `d12-001`, `experiments/d12/`, on `data/pons/d11-backfill-v1` unchanged — no collection, no RPC, no live hour in this wave (the frozen test is the deliverable; a live hour is a later owner decision). Same cutoff T (t0 + 30,240 s), same 30-s tick grid, same LEARNING and FROZEN partitions and boundary rules as `d11-001`, so the FROZEN grid rows, their evaluator labels and the REFERENCE scores (AUC 0.5885) are the same objects and are reused from `experiments/d11/runs/d11-001/grid/` (`labels.jsonl`, `scores_reference.jsonl`), with a recomputation check on at least 200 rows (identical valences at 1e-9 Hz, since seeds and weights are the same). Fixed: clean reference `ba95b605…`, `pons_encoder_v2` (schema `3bf4f34c…`), `admission_v2`, readout k = 8 with `comparison_v1` seeds, the k = 8 decoder, horizon 900 s, latency 2 s, the plasticity operator and its learning rate, no forgetting. The absolute rule of D10/D11 stays byte-identical behind `reinforcement.rule = absolute_profit_v1`; the new rule is selected by `reinforcement.rule = relative_cohort_v1`. PONS is not touched; no wallet feature enters the brain.

**2. School mode, defined.** The LEARNING branch opens no paper position and holds none. At every LEARNING tick, every `admission_v2`-eligible candidate (no cap of 6, no rotation, no hold mode) is presented with the standard readout, its valence is recorded, and its eligibility trace is stored as a pending lesson keyed (cutoff_ts, stable_id). The trace is formed exactly as the D11 learning path forms it for a decision — same replicates, same aggregation; nothing changes in the plasticity rule, only where sign and amount come from and what triggers them. A lesson matures at the first tick whose cutoff ≥ lesson cutoff + 902 s; matured lessons of one cohort are applied together, in `stable_id` order, before that tick's presentations. Lessons with cutoff + 902 > T are discarded, counted, never applied. No lesson is ever applied at a FROZEN tick. Presentations without a matured lesson change no weight.

**3. The relative signal, `relative_cohort_v1`.** Cohort = the eligible candidates of one tick that have a settled evaluator label (D11-001 addendum 8, the same integer-exact code); UNRESOLVED members leave the cohort and are counted. With n the cohort size after drops and ranks ascending by net with average ranks for ties, s_i = 2·(rank_i − 1)/(n − 1) − 1 ∈ [−1, +1]: worst −1, best +1, mean exactly 0 per cohort. n < 3 → no lesson for that cohort, counted. s > 0 is a reward and s < 0 a punishment of amount |s|; s = 0 is neutral, no update (the existing neutral treatment). No clipping can occur; `REINFORCE_CAP` and `reinforce_full_scale` are not consulted by this rule. Known answer, both owner examples: +14/+3/−2/−7/−18/−61 % and −3/−8/−15/−28/−50/−82 % both give s = +1, +0.6, +0.2, −0.2, −0.6, −1. The financial net (wei) and the pedagogical signal s are two columns on every LESSON record and are never merged. Rank rather than z-score because it is scale-free, immune to the tail that saturated two calibrations, and zero-mean by construction.

**4. Register-then-compute.** (i) This spec commit. (ii) `experiments/d12/PLAN.md` and the run configuration alone: rule (3) with n_min, the maturity rule, the primary and secondary grids (6), the statistics (7), the learning-curve and weight diagnostics (8), the inconclusive conditions (9), the mirror diagnostic definition (5). (iii) Numbers only, no brain: the lesson ceiling (eligible candidate-ticks in LEARNING with cutoff + 902 ≤ T in cohorts of n ≥ 3, from the market-only tracker), the cohort-size distribution, the primary and secondary FROZEN row counts and class balances, and the mirror diagnostic (5). Then the run.

**5. The mirror diagnostic on the existing d11-001 scores (the owner's cheap account, before any new run).** From `grid/scores_trained.jsonl` and `grid/scores_reference.jsonl`, rows VALID in both: Pearson r, Spearman ρ and Kendall τ between trained and reference valence; OLS trained = a + b·reference with R²; the fraction of row pairs whose order is reversed; the same per temporal block and within tick (cohort-wise τ, the quantity that matters for ranking); AUC(−reference) beside AUC(trained), and the residual of AUC(trained) from 1 − AUC(reference). Wording: numbers. The mechanistic reading — fifteen punishments depressed the approach pathway in proportion to the prior valence, so the trained valence is a decreasing affine function of the untrained one — is a hypothesis that the slope b and τ test; it is not a finding until stated as such by the owner. Written to `experiments/d12/mirror_diagnostic.md` in commit (iii).

**6. Primary and secondary grids.** Same grid machinery as `d11-001`. Primary = FROZEN rows on tokens that were never a lesson (first `admission_v2` eligibility ≥ T): the owner's "tokens she never received as lessons". Secondary = all FROZEN rows, for comparability with d11-001's 5,013. Branches SCHOOL (final LEARNING checkpoint) and REFERENCE (clean, reused scores); digests verified before and after every scoring pass.

**7. Statistics.** As D11-001 addendum 9: ΔAUC = AUC(SCHOOL) − AUC(REFERENCE), Mann–Whitney with ties ½, paired cluster bootstrap by `stable_id`, 10,000 resamples, seed 20260913, 95 % percentile interval, overall and per temporal block, on the primary and on the secondary grid. Pre-registered readings: interval entirely above 0 → "the school-trained ranking of later tokens is higher than the untrained one, not compatible with sampling variation"; interval including 0 → "compatible with sampling variation"; interval entirely below 0 → "the inversion persists". No "significant", no "proves". Descriptive beside it: Spearman(score, net) per branch, the per-row score difference, the suppression check (BUY-crossing per branch, overall and by later outcome class).

**8. Learning curve and weights, descriptive.** For every lesson: valence at presentation and the s that arrives 902 s later. Rolling over LEARNING, every 500 applied lessons: Spearman between valence-at-presentation and s, and mean within-cohort Kendall τ — prospective by construction, since the brain has not yet been taught those lessons when it scores them. Every 500 lessons: mean, norm and the fraction of plastic KC→MBON weights at floor or ceiling, with the checkpoint digest.

**9. Inconclusive conditions, pre-registered, not loosened after the run.** (1) fewer than 2,000 lessons applied; (2) fewer than 100 paired labels on the primary grid; (3) either outcome class under 20 on the primary grid; (4) paired coverage under 95 %; (5) encoder saturation over 5 % of (row, channel) pairs or INVALID_STATE over 5 %; (6) more than 25 % of plastic synapses at floor or ceiling at the end of LEARNING. The secondary grid is reported regardless of the verdict.

**10. Determinism.** The first 100 LEARNING ticks of the school replay run twice → identical checkpoint digest and identical sha256 of the LESSON log; a test. The full run is not repeated.

**11. Frozen loop branches, descriptive.** SCHOOL and REFERENCE replays over FROZEN with paper trading as in d11-001 (one position at a time, `SETTLED_FROZEN`, digests unchanged); their PnL and action frequencies are the paper results. The LEARNING branch has no paper results by design, and the report says so.

**12. Records.** LESSON: cutoff_ts, stable_id, cohort n, net (wei), rank, s, applied_at_tick, checkpoint digest after. ROUND records for every presented candidate as today. Per tick: pending-lesson queue size, lessons applied, lessons discarded by reason (UNRESOLVED, n < 3, boundary).

**13. Untouchables, tests, gate, docs.** `git diff --stat <this spec commit> -- experiments/d10 experiments/d11 data/pons upstream tests/upstream_audit experiments/d7 experiments/d8 experiments/d9b experiments/historical/runs` empty at close; D10 and D11 configurations behave byte-identically (existing tests). `tests/d12/` mapped to the owner's paragraphs: school mode (no position, all eligible presented), the relative signal (known answers of addendum 3, ties, n < 3), maturity and no lookahead (a lesson can never be applied before cutoff + 902 s, nor at a FROZEN tick), the token-disjoint primary grid, the mirror diagnostic on toy data (an exact negative gives τ = −1, b = −1), the learning curve, the inconclusive conditions, the rule selector leaving the absolute path untouched. Affected suites while working; the full gate twice at close only. HANDOFF block ≤ 25 lines; PLAN.md one section; no research document. Deviations declared, none absorbed. No RPC, no live, no real money.

**14. Compute bound.** About 105 k school presentations (≈ 1,009 ticks × ≈ 13 eligible × 8 replicates), the SCHOOL scoring pass on the grid (≈ 41 k) and two frozen loops (≈ 40 k): roughly two neural hours at the hist-003 rate. One Opus agent, sequential.

## P1 — product: the scientific track stops; frozen trader, continuous Pons paper loop, spectacle feed — canonical decision (owner, 2026-09-13, Portuguese, verbatim)

Agora eu pararia a trilha científica. Sem D13 para "achar alpha".

A D12 respondeu a pergunta que faltava: mesmo dando 19.665 lições balanceadas, a escola não ensinou ranking. A mosca treinada ficou pior que a virgem: AUC 0,434 contra ~0,567, praticamente parou de comprar e passou a dar muito mais NO_RESPONSE. A curva de aprendizado ficou em torno de zero. Isso não é "faltou mais dado"; é o mecanismo atual de memória entrando no caminho errado para esse uso.

O achado técnico é bem claro: esse mushroom body implementado aprende principalmente por depressão de KC→MBON. Com só punição, ele deprimiu uma via e a mosca ficou medrosa. Com reward e punishment balanceados, ele foi deprimindo as duas e a mosca foi ficando silenciosa. O "forget/recovery" existe no modelo upstream, mas nem estava sendo chamado no loop da Pons. Então a memória atual é muito mais "apagar conexões" do que escrever uma estratégia.

Minha decisão seria:

acabou a obrigação de a mosca aprender trading.

Para o produto, eu usaria a mosca virgem/frozen como trader — porque ela ainda toma decisões e não vai morrendo neurologicamente ao longo do dia — e preservaria todo o histórico científico como lore real:

"we tried to train it; it got traumatized and stopped trading."

Isso é até engraçado pra caralho.

Se quisermos memória no espetáculo, eu faria depois uma versão de produto com recovery/forgetting ligado, não como tentativa de provar alpha, mas para a mosca não ficar permanentemente catatônica depois de uma sequência ruim. Aí podemos ter temporadas e personalidade sem ficar prometendo que ela aprende a prever mercado.

Então agora eu faria só estas três coisas:

Congelar o cérebro trader funcional — checkpoint limpo/virgem, sem mais school mode.
Ligar Pons continuamente — ela cheira candidatos vivos, escolhe, compra/vende em paper e produz acontecimentos.
GPT/Astra transformam isso em espetáculo — SNIFFING, FLY PICKED, posição, cérebro, PnL, REWARD/PUNISHMENT, histórico, maior win/loss, tokens rejeitados etc.

E eu não gastaria mais uma madrugada tentando fazer 0.434 virar 0.53.

A ciência já nos deu uma história suficiente: a mosca consegue ser condicionada, mas o mecanismo de plasticidade usado não conseguiu aprender a ranquear memecoins e, quando treinado demais, silencia o próprio comportamento.

Agora é produto.

### Fable addenda (reviewer, 2026-09-13) — binding for the P1 wave

The owner closes the scientific track and opens the product. These addenda turn the three items into one bounded wave whose only success condition is operational: the frozen fly runs, survives a restart, and feeds the spectacle. No number produced here is a result.

**1. Decision and scope.** No D13, no school mode, no plasticity in the product loop, no change to any threshold, scale, admission constant or reinforcement scale, no wallet feature in the brain, no signing, no funds, no key material in any artifact. The product never claims prediction; the scientific record (`docs/SPEC.md`, `the session log`, the `results.md`/`report.md` files) is the lore and is not rewritten. Three deliverables: (A) the frozen trader brain, (B) the continuous Pons paper loop, (C) the spectacle feed contract. The spectacle itself (owner item 3, GPT/Astra) is not in this wave; this wave delivers the surface it reads.

**2. The trader brain, `trader-v1`.** The clean reference of `d11-001`/`d12-001`, digest `ba95b605…` — the checkpoint the school started from and `frozen_reference` reproduced to the wei (the agent verifies the full digest and its provenance before copying anything). Stored as a versioned artifact under `brains/trader-v1/`: `brain.npz` and `manifest.json` (full checkpoint digest, graph digest, `pons_encoder_v2` input-schema sha256, the sha256 of the D11 configuration it belongs to, provenance commits and run ids, `learning: FROZEN`). Tests: loading yields the registered digest; a loop of N ticks with learning FROZEN and at least one settled episode ends with the same digest (the no-plasticity invariant). The wei-exact replay reproduction is not repeated — `frozen_reference` in `d12-001` already is that proof.

**3. The continuous loop.** `LiveDriver`/`PonsLoop` as `d10-live-001` ran them, with the `d11-001` object — `admission_v2`, `pons_context_v2`, `pons_encoder_v2`, readout k = 8, horizon 900 s, cadence 30 s, one position at a time, the same paper execution and settlement model — learning FROZEN, brain `trader-v1`. What differs from `d10-live-001`, each a key in one committed configuration file (`product/pons_live.json`, or the location the repo's conventions suggest): (a) no wall-clock stop — the loop stops on the stop file, SIGTERM/SIGINT, or an invariant violation (digest mismatch at start, `eth_chainId` ≠ 4663), never on a transient error; (b) the request budget is a rolling hourly cap (D10's 3,000 per hour unless the agent documents a better value); at the cap the loop emits `THROTTLED` and waits for the window, it does not exit; (c) resume — on every start the brain is loaded from `trader-v1` and its digest asserted, and account, open position, pending confirmations and last cutoff are restored from the durable state the previous process wrote; a position open across a restart stays open and is never closed at a restart mark; (d) RPC errors retry with backoff and are written as `RPC_ERROR` events with counters; (e) `HEARTBEAT` every tick with request counters, account, open position, uptime; (f) the existing absolute reinforcement rule computes REWARD / PUNISHMENT / NEUTRAL for every settled episode and it is written to the journal as a `CREDIT` event and **not applied** to any weight — a test asserts the digest is unchanged after a settled episode.

**4. Journal and state — the feed.** Append-only JSONL under `data/pons/live/` (one file per UTC day, `events-YYYY-MM-DD.jsonl`, gitignored, never committed) with the existing record kinds plus the product kinds; and `state.json` in the same directory, rewritten atomically after every event, holding: account (bankroll, realised PnL, unrealised mark, in wei with an ETH rendering), open position (token, entry price and time, size, age, last mark, PnL), the last pick with its brain snapshot (valence in Hz, MBON outputs, KC active count, the k = 8 readout, the action), the last N events, the closed-episode history with PnL and credit label, biggest win and biggest loss, rejected candidates with admission-reason counts (session and last hour), candidates sniffed per tick, request counters, loop health (uptime, last tick, throttled, error counts, brain digest). The owner's vocabulary maps onto kinds: SNIFFING = one `SNIFF` event per tick listing the candidates seen with their admission outcome (never one event per candidate); FLY PICKED = `PICK`; position = `OPEN` / `MARK` / `CLOSE`; brain = the snapshot on `PICK`; PnL on `MARK` / `CLOSE` and in the account; REWARD/PUNISHMENT = `CREDIT`; history = closed episodes; biggest win/loss; tokens rejected = the `SNIFF` outcomes and their reason counts. No endpoint, no key, no PII in either file. `docs/SPECTACLE_FEED.md` documents both files, key by key, with one real example from the proof run — the single place the contract lives; GPT/Astra read that file and nothing else.

**5. Operation.** `the live-loop launcher` with `start`, `stop`, `status`, `tail`; a systemd **user** unit `the-pons-user-unit` (`Restart=on-failure`, a `RestartSec`, `EnvironmentFile` pointing at the same `.env` `d10-live-001` read, by key name, never echoed), installed under `~/.config/systemd/user/`. No `sudo`, no `loginctl enable-linger` — the unit stops at logout unless the owner enables linger, and the HANDOFF says so. `status` prints account, open position, the last 10 events, requests this hour, uptime, brain digest. Logs go to journald and to the loop's own JSONL.

**6. Proof in the wave.** One live paper session of at least 60 minutes, run in the background while tests and docs are written: send SIGTERM near the midpoint, restart, and show resume (account, cutoff, open position carried over; digest asserted at both starts). Report: ticks, requests (backfill and steady-state per hour), events per kind, candidates sniffed / rejected / picked, episodes, errors, reorgs, peak RSS. Then start the service and leave it running; the stop command is one line in the HANDOFF. RPC bound for the wave: three times the hourly cap. Every number from the run is descriptive; there is no verdict, no hypothesis and no success condition beyond "it runs, it resumes, it feeds".

**7. Untouchables, tests, gate, docs.** `git diff --stat <this spec commit> -- experiments data/pons/d11-backfill-v1 upstream tests/upstream_audit flytrade/mushroom.py` empty at close; the D10, D11 and D12 configurations behave byte-identically (existing tests). `tests/product/` mapped to these addenda: the `trader-v1` digest, the no-plasticity invariant, resume from durable state, the hourly throttle, `CREDIT` recorded and not applied, a `state.json` validator with the documented keys, the new kinds in the observer projection vocabulary (declared, as D11 and D12 did for `LESSON`), and the existing no-key guard extended to every new file. Affected suites while working; the full gate twice at close only. HANDOFF block ≤ 25 lines, in the (n) slot. No research document, no PLAN.md, no register-then-compute — this is product, nothing here is a measurement. Deviations declared, none absorbed. `~/Documentos/PONS` is not touched.

**8. Not in this wave, queued for the owner.** Product memory v2 with recovery (`mb.forget()` or a registered decay of gains toward 1.0, so depression is transient and only consistently reinforced patterns stay depressed) for seasons and personality — after the spectacle exists, never as an alpha claim. The spectacle (GPT/Astra). Any HTTP surface. Wallet identity in PONS.

**9. Cost.** One Opus agent, sequential; the proof run occupies wall clock, not tokens. Expected at or below the D12 order (≈ 1 M tokens), since the live driver, paper model, admission and encoder already exist and only the run lifetime, resume, `CREDIT`, `state.json` and the service are new. RPC ≈ 500 requests of backfill plus steady-state polling under the hourly cap.
