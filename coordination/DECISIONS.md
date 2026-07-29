# Decisions

Orchestrator and synthesizer decisions. Append only unless a synthesizer revises with a clear supersession note.

## D-0001 — Planning-only phase

**Status:** active  
**Date:** 2026-07-27  

This phase is high-level product and architecture planning only. No product code implementation.

## D-0002 — Auditable shared surface

**Status:** active  
**Date:** 2026-07-27  

All work must be auditable on the shared repository surface (`SWARM.md`, `coordination/`).

## D-0003 — Obsolete documentation removed

**Status:** active  
**Date:** 2026-07-27  

Old documentation is obsolete and must be removed. Prior `README.md` and `docs/DESIGN.md` are not authoritative.

## D-0004 — Eight independent specialist workstreams

**Status:** active  
**Date:** 2026-07-27  

Decompose first-pass planning into eight independent specialist workstreams:

1. product doctrine
2. causal diagnosis
3. counterfactual environments
4. reward integrity
5. intervention/update layer
6. evaluation/deployment gates
7. platform architecture
8. adoption/economics

**Rationale:** Independent proposals reduce correlated blind spots before synthesis.

## D-0005 — Isolate concurrent writes

**Status:** active  
**Date:** 2026-07-27  

Research agents own only their named log under `coordination/agents/` and their proposal under `coordination/proposals/`. Central deliverables remain synthesis-owned.

**Rationale:** Preserve auditability and prevent merge conflicts.

## D-0006 — Cross-cutting analyses before synthesis

**Status:** active  
**Date:** 2026-07-27  

Add three cross-cutting analyses before synthesis:

1. interface and contradiction matrix
2. falsifiable research program
3. end-to-end threat model

**Rationale:** Domain proposals alone can miss seam failures, weak falsifiability, and systemic abuse paths.

## D-0007 — Einstein synthesis authority

**Status:** active  
**Date:** 2026-07-27  
**Owner:** einstein (synthesis)

Public documents `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, and `RESEARCH.md` are the authoritative planning surface. Specialist proposals under `coordination/proposals/` remain historical inputs and peer-review records. On naming, ownership, promote-path rules, and wedge proof criteria, the public docs and this decision log win.

**Rationale:** Independent proposals necessarily diverge; one coherent end-to-end system requires a single synthesis cut.

## D-0008 — Canonical artifact catalog and alias retirement

**Status:** active  
**Date:** 2026-07-27  

Adopt the frozen kind catalog in `ARCHITECTURE.md` §5.1. Digests are identity; URIs are locator hints only. Public synonyms are retired to the alias map in §5.2 (adapters may translate). Platform promote-path kind for adversarial validation is `RewardValidationReport` (⊇ feynman `AdvRewardReport` fields). Darwin sketch interventions are named `InterventionSpec`; Turing keeps `InterventionRecord`. Provenance splits into `AssertionProvenance` vs `ArtifactProvenance`.

**Rationale:** Resolves Hopper↔Maxwell vocabulary collision (P0-1), URI vs digest (P0-4), and Galileo duplicate-concept table. Preserving synonyms as first-class kinds guarantees dual registries.

## D-0009 — Enum prefix scheme

**Status:** active  
**Date:** 2026-07-27  

Cross-layer text must use prefixed enums: `claim.G*`, `cert.G*`, `split.S*`, `adopt.S*`, `fidelity.L*`, `risk.R*`, `breach.S*`, `repro.constructed_elicitation` / `repro.independent_recovery`. Bare “S3” / “G3” are forbidden in shared docs.

**Rationale:** Five proposals overloaded S0–S7 and G0–G10 with incompatible meanings (Galileo §4.1).

**Lovelace clarify (2026-07-27):** Prefix table extended by **D-0028** (`gate.G0–G6`). Do not use `adopt.G*`.

## D-0010 — Constructed elicitation vs independent recovery

**Status:** active  
**Date:** 2026-07-27  

`repro_status` is split into `constructed_elicitation` and `independent_recovery`. Constructed elicitation may support regression/elicitation suites and must be labeled. It must **not** alone raise `claim.G*` to G3+, authorize `RewardCertificate` for optimize paths, or count as causal confirmation. Only independent recovery may support those rises.

**Rationale:** Darwin↔Noether peer reviews (R3); Feynman R6; Bohr H6/E3. Without the split, generators false-confirm causes they baked into fixtures.

## D-0011 — IdentificationPlan required for causal grade rise

**Status:** active  
**Date:** 2026-07-27  

Before claim grades may rise via intervention evidence, and before bundles may gate updates that claim causal support, an `IdentificationPlan` must include predicted Outcome patterns for: (1) **primary** causal flip, (2) **placebo** edit, (3) **rival** flips for top alternatives. Non-separating patterns set `distinguishability=unresolved` and block grade-raising. `CompilePackage` with `compile_status=compilable` is required before env/task materialization; hollow `specification_ref` is refused (`NeedsMoreEvidence`).

**Rationale:** Darwin R2 / Noether compile gap; Galileo M-ident / M-compile. Primary+placebo alone leaves D1–D3 clusters observationally equivalent.

## D-0012 — Held-out AccessClass and taint closure are architectural invariants

**Status:** active  
**Date:** 2026-07-27  

Every artifact carries `AccessClass` ∈ {`open`, `tune`, `sealed`, `red_team_private`}. Sealed/red-team bodies are invisible to update/train job credentials; eval workers receive short-lived handles only. `TaskSuite` must carry `split` + `sealed`. Promote path requires `taint_closure_clean=true`: break-glass debt, contamination, revoked-cert parents, and non-promote L1 flags cannot launder into closure. Process controls augment; they do not substitute for AccessClass enforcement.

**Rationale:** Hopper↔Maxwell P0-3; Pasteur SI3/SI8; Maxwell I1. Honor-system held-out fails open under pressure.

**Lovelace clarify (2026-07-27):** Enforcement timing for the reference path is **D-0032** (executable same-node sealed-fetch deny before held-out claims). Fleet pools remain deferred.

## D-0013 — Platform enforcement vs statistical policy ownership

**Status:** active  
**Date:** 2026-07-27  

Hopper owns artifact registry, control/data/execution planes, policy engine, run ledger, job admit, deploy authorize, and AccessClass enforcement. Maxwell owns split taxonomy, seal schedule, scorecard schema, statistical plans (MDE/α/UCB), contamination *criteria*, and promote/hold/rollback *recommendations*—emitted as artifacts, never as a second control plane. Canary is a ledgered StageRun, not a side daemon.

**Rationale:** Hopper peer review P0-2; Galileo X4; Pasteur XC1. Dual control planes create fail-open gaps.

## D-0014 — Reward validation mandatory on every promote

**Status:** active  
**Date:** 2026-07-27  

Every promote-path `DeployDecision` must reference a `RewardValidationReport` digest. The stage always runs. Allowed status: `structure_only` → `not_applicable`; `reward_dependent` → live `certified` (not provisional) with no open `breach.S2–S3`. Probe *depth* may scale by update kind; artifact *presence* may not. Cost/EVI must not omit the digest. Vacuous “search found none” without planted-bug catch is not a green adversarial claim. Revoke emits `UpdateInvalidateEvent`; Turing executes block/rollback/quarantine.

**Rationale:** Resolves Maxwell parallel-optional vs Hopper I9 / Feynman fail-closed (P1-4); Curie/Faraday vacuous-probe findings; joint Feynman↔Turing admit_class freeze.

## D-0015 — Admit class and least-risk reversible interventions

**Status:** active  
**Date:** 2026-07-27  

`admit_class` is a property of selection procedure + payload, not type id alone (`structure_only` vs `reward_dependent` per Turing §5.1 / Feynman §18.3). Decision policy chooses the **least `risk.R*`** (smallest blast radius) among candidates that clear effectiveness gates. Satisficing prefers R0–R2 before R3. Every applied `InterventionRecord` has non-empty `rollback_spec` before promote; promote forbidden without deploy-adapter rollback capability (atomic or dual-run). Wedge automates `structure_only` only; `reward_dependent` is out of the lovable bar.

**Rationale:** Turing satisficing + Feynman admit-class joint freeze; Curie memory/policy-first hardened to structure_only; Pasteur SI7/SI9.

**Lovelace clarify (2026-07-27):** Compensating rollback completeness for memory/side effects is **D-0033**.

## D-0016 — Rollback, abstention, and reject are successful outcomes

**Status:** active  
**Date:** 2026-07-27  

Hold, explicit reject, abstain (verifier), and rollback are first-class successful terminals when warranted. They close a loop cycle with lineage. Anti-metrics must not punish honest rollback or reject. “Silent hope” and undocumented patches are failures.

**Rationale:** Curie I7; Faraday rollback-as-win; Maxwell I6; operator trust requires celebrating guards that fire.

## D-0017 — Wedge proves loop closure, not artifact volume

**Status:** active  
**Date:** 2026-07-27  

> **Superseded for full-loop proof: see D-0029.** Do not use the historical “hashes / partner affidavit acceptable” sentence below as authority for “full loop proven.”

The open-source wedge is: one reference harness, one recurring failure class, one reversible non-weight `structure_only` update, recorded/redacted evidence, deterministic replay, counterfactual contrasts, adversarial validation stage, sealed held-out, and a guarded deployment decision (ship or rollback) with evidence re-entry hashes. Quality bars (reproduction attestation, seed stability) precede task count. `adopt.S0` offline harness completion is **smoke only**. “Full loop proven” requires executed DeployDecision + re-ingested evidence hashes (partner canary affidavit acceptable; docs/YAML-only not). Marketing forbid: offline success + documented canary config must not be called full loop proven, adversarial-reward complete, or safe to optimize.

**Rationale:** Curie peer review of Faraday C1/C2/C3/M1/M2; claim split Curie §21; Faraday §6 rewrite demand.

**Supersession note (2026-07-27):** Affidavit / evidence-hash clause superseded by **D-0029** (CAS `EvidenceBundle` re-entry + `EvidenceReentryPlan` required for full loop proven; hash list alone = canary-affidavit provisional). Lovelace R-02: lead-in above makes the supersession impossible to miss without rewriting history.

## D-0018 — Local/sovereign default; portable digest-addressed artifacts

**Status:** active  
**Date:** 2026-07-27  

Open core defaults to local single-tenant control + data plane with no hard hosted dependency for the loop. Evidence stays under tenant residency and redaction policy. Export is an explicit policy job with `RedactionAttestation`. Interchange uses content-addressed digests and versioned schemas—not exclusive hosted formats.

**Rationale:** Hopper A3/I6; Faraday I3; Pasteur SI11. Sovereignty and portability are product properties, not post-MVP polish.

## D-0019 — Threat controls are roadmap gates

**Status:** active  
**Date:** 2026-07-27  

Pasteur security gates SG0–SG7 and hard stops are binding roadmap blockers recorded in `ROADMAP.md`, not an appendix. Minimum safe defaults (redact-on-ingest, deny-live, fail-closed promote, no contamination waiver, break-glass taint, R0–R2-only early automation) are open-core acceptance criteria.

**Rationale:** User-required synthesis resolution; Pasteur §13; without gate binding, threat models become unread literature.

## D-0020 — Invariant core vs deferred scale

**Status:** active  
**Date:** 2026-07-27  

Invariant core: digest lineage, AccessClass + taint, RewardValidationReport on promote, IdentificationPlan + repro split, structure_only decision policy, local open core, fail-closed parents, redact-on-ingest, deny-live, TTVI-first metrics. Deferred until after wedge proof / named gates: multi-tenant hosted GA, R3 automation, second harness, pack marketplace, embedding near-dupe at scale, L3-live default, ecosystem vanity KPIs, multi-region failover.

**Rationale:** Curie minimum surface; Faraday I5; Hopper open-core test; Galileo monolith warnings. Scale features must not redefine the wedge.

## D-0021 — Metric stack and north-star

**Status:** active  
**Date:** 2026-07-27  

Primary metric: **TTVI** (time-to-validated-improvement), including lineage-complete reject as a valid terminal. Concurrent gates: contamination=0; non-vacuous probes when adversarial completeness is claimed; canary move-or-rollback. Cost/cycle secondary. Ecosystem metrics null until adopt.G4. Anti-metrics as in `README.md`.

**Rationale:** Curie §8; Curie review R-metrics vs Faraday unordered dashboards (C4).

**Lovelace clarify (2026-07-27 / R-03):** Historical body token `adopt.G4` is **forbidden**. Normative reading: ecosystem metrics null until **`gate.G4`** (Faraday stop/go; D-0028). Adoption stages remain `adopt.S*`; eval splits `split.S*`; reward breaches `breach.S*`; causal grades `claim.G*`. Do not invent `adopt.G*`.

## D-0022 — Thesis falsifiers adopted

**Status:** active  
**Date:** 2026-07-27  

Adopt Curie F1–F7 as thesis kill/narrow criteria, bound to Bohr experiments E1–E6/E4/E9/E10 and roadmap kill switches K1–K6, published in `RESEARCH.md` and `ROADMAP.md`. Falsification is a feature; prefer honest pivot over metric theater.

**Rationale:** Required synthesis resolution; D-0006 research-program intent.

## D-0023 — Research ownership and first implementation spine

**Status:** active  
**Date:** 2026-07-27  

Bohr owns experiment portfolio sequencing (merged into `RESEARCH.md`). Domain peers own method internals. When D-0001 lifts, the first implementation spine is E1→E2→E6→E5→E4 over platform breadth. Engineering conformance (sealed deny, promote closure, deny-live, secret quarantine) is validation, not research success.

**Rationale:** Bohr synthesizer asks; prevents platform-first delay of kill/prove evidence.

**Lovelace clarify / supersession (R-01, 2026-07-27):** The **structure_only critical spine** is **`E1→E2→E5→E4`**. **E6** is a **non-blocking parallel** experiment and a **`reward_dependent` freeze switch only** — **never** a prerequisite for a green structure_only `DeployDecision`. Prior body wording “E1→E2→E6→E5→E4” is superseded. Matches ROADMAP/RESEARCH post F-09, Lovelace §12.3, and Bohr §18.2–§18.3.

## D-0024 — Planning phase remains in force

**Status:** active  
**Date:** 2026-07-27  
**Supersedes:** none (affirms D-0001)

Synthesis produces documentation and coordination ledger only. No product code. No alteration of `.cursor/mcp.json`. No commit unless a human explicitly instructs.

**Rationale:** Explicit constraint on the synthesis assignment.

## D-0025 — RewardValidationReport §25.3 field freeze

**Status:** active  
**Date:** 2026-07-27  
**Supersedes:** none (refines D-0008 / D-0014 field detail)

`RewardValidationReport` carries the turing §5.3 / feynman §18.4 field set plus feynman §25.3 additives: required `schema_version`; optional `report_digest` that **MUST** equal the CAS content digest when present; well-formedness invariants `(not_applicable ⇔ !reward_dependent)`, `(certified ⇒ certificate_id ∧ expires_at ∧ budget_remaining)`, and `reward_dependent` bool matching `InterventionRecord.admit_class`. Authoritative text: `ARCHITECTURE.md` §5.5.

**Rationale:** Feynman reward-lane synthesis review (§36 residual 1); closes peer freeze without blocking contradictions.

## D-0026 — R6 null-result / top-k bridge

**Status:** active  
**Date:** 2026-07-27  

Darwin R6 / feynman §32 bridge is normative: `RivalStatus.adv_reward_null_result=true` only when `RewardValidationReport` is `certified` with no open `breach.S2–S3` **and** `repro.independent_recovery`. Task-oracle uplift, constructed elicitation, and provisional never count as null-result. Top-k default k=3 ranked `claim_grade → severity → confidence`; supported+open S2/S3 `reward_misspec_*` cannot be ranked out of the R6 gate set. Authoritative text: `ARCHITECTURE.md` §8.1.

**Rationale:** Feynman §36 residual 2; bilateral Darwin↔Feynman freeze lacked a numbered D-item.

**Clarify (2026-07-27, feynman §37 / §32.2):** Rank universe = in-play rivals (`open|supported|unidentified`), excluding cleared (`weakened|rejected` ∧ `adv_reward_null_result=true`). The `top-k ∩ reward_misspec_*` formula is unchanged once “rivals” means that universe.

**Lovelace clarify (R-03, 2026-07-27):** Historical phrase “open S2/S3” in the body means **`breach.S2–S3`** only — not `split.S*`, `adopt.S*`, or `gate.G*`. Ranking key `claim_grade` is Darwin **`claim.G*`** strength. Keep prefixes consistent with D-0009 / D-0028.

## D-0027 — Deterministic criterion identity vs judge-pack disjoint

**Status:** active  
**Date:** 2026-07-27  

Judge packs for train reward / adv battery / sim primary / panel utility remain disjoint. A `judge_class=deterministic` checker identified solely by `criterion_id+version` (no pack, exemplars, learned weights, or mutable prompts) is shared criterion identity, not a judge pack, and may be referenced across those sides. Embedded packs or mutable prompts reclassify the checker under the full disjoint-pack rule. Authoritative text: `ARCHITECTURE.md` H2 oracle/judges row.

**Rationale:** Feynman §36 residual 3 / noether↔feynman §26 clarify.

## D-0028 — Faraday stop/go prefix is `gate.G0–G6`

**Status:** active  
**Date:** 2026-07-27  
**Supersedes wording in:** D-0009 (extends prefix table), D-0021 (replaces `adopt.G4` token)

Faraday adoption **stages** remain `adopt.S0–S7`. Faraday stop/go ladder is **`gate.G0–G6`**. Eval splits remain `split.S*`. Reward breaches remain `breach.S*`. Causal grades remain `claim.G*`. The token `adopt.G*` is forbidden. Small sealed suite nickname is `split.S3-mini`. Authoritative prefix table: `ARCHITECTURE.md` §5.3.

**Rationale:** Lovelace F-01; D-0009 forbids bare/colliding enums; `adopt.G4` invented a third ladder.

**Note on D-0021:** where D-0021 said “ecosystem metrics null until adopt.G4,” read **`gate.G4`**.

## D-0029 — Full loop proven requires CAS EvidenceBundle re-entry

**Status:** active  
**Date:** 2026-07-27  
**Supersedes affidavit clause in:** D-0017

**Full loop proven** requires all of: (1) ledgered `DeployDecision` (ship or rollback), (2) post-canary episodes ingested as redacted `EvidenceBundle` digests in a permitted **local or tenant-private CAS** under the same `failure_class`, (3) `EvidenceReentryPlan` outcome recorded. A public or shared **hash list alone** is at most **canary-affidavit provisional**, never full closure. YAML/docs-only canary remains invalid. Public disclosure of sensitive content is **not** required for open-source proof.

**Rationale:** Lovelace F-02 (P0 residual of Curie C1); closes H7 hole on partner-affidavit path.

## D-0030 — RewardValidationReport field freeze (audit affirmation)

**Status:** active  
**Date:** 2026-07-27  
**Affirms:** D-0025  
**Refines:** D-0014 (adds field-level freeze detail)

`RewardValidationReport` fields and status/`admit_class` well-formedness in `ARCHITECTURE.md` §5.5 are normative for promote-path closure. Implementations that emit a differently shaped “report” do not satisfy D-0014. Issuer = reward integrity; enforce-at-apply = update layer (unchanged).

**Rationale:** Lovelace F-03; peer freezes (Feynman §25.3 / Turing §5.3) must live in ledger + architecture, not only bilateral notes.

## D-0031 — RedactionAttestation canonical; DecisionTrace embedded

**Status:** active  
**Date:** 2026-07-27  
**Refines:** D-0008 catalog

`RedactionAttestation` is a **canonical §5.1 kind** (owner: pasteur policy / hopper store) with digest identity and minimum fields in `ARCHITECTURE.md` §5.1. `DecisionTrace` is **not** a separate kind — it is an **embedded required field** of `InterventionRecord`. Alias map splits catalog vs supporting types (`ARCHITECTURE.md` §5.2).

**Rationale:** Lovelace F-04 / F-07; SG0 and H0/H4 required these without catalog identity.

## D-0032 — Executable same-node sealed-fetch deny on wedge path

**Status:** active  
**Date:** 2026-07-27  
**Clarifies timing in:** D-0012

AccessClass sealed invisibility remains an architectural invariant. Before any “held-out sacred” / sealed-gate claim on the **reference wedge path**, an **executable same-node sealed-fetch denial** must pass (train/update credentials cannot materialize sealed bodies). Deferred to Track A / SG7: *distributed/fleet sealed pools* and multi-tenant sealed worker isolation — **not** the deny itself. Process controls remain augment-only.

**Rationale:** Lovelace F-06; prevents spec-only sacred held-out during 0–6w.

## D-0033 — Compensating rollback for memory and external side effects

**Status:** active  
**Date:** 2026-07-27  
**Refines:** D-0015

For `explicit_memory` or updates with external/durable side effects, `rollback_spec` must list compensating actions **or** mark `rollback_incomplete` ⇒ promote deny. SG5 / chaos drills must exercise the compensating path; config-pin-only drills do not clear those update types for “loop proven.”

**Rationale:** Lovelace F-08; Pasteur AC-D1/AC-U3.

## D-0034 — Reproduction attestation ownership

**Status:** active  
**Date:** 2026-07-27  

Noether **emits** repro attestation flags on `CounterfactualBundle` (pre-update fail under seeds, placebo/contrast results). Darwin supplies **preconditions** via `CompilePackage` / diagnosis locus binding. Faraday/Curie **consume** attestation as adoption / wedge proof criteria only — they do not own a third schema.

**Rationale:** Lovelace F-11; Galileo Q3.

## D-0035 — Lovelace audit repair batch accepted

**Status:** active  
**Date:** 2026-07-27  

Accept Lovelace verdict **accept with required fixes**. Implemented F-01, F-02, F-03, F-04, F-05, F-06, F-08 (required) and F-07, F-09, F-10, F-11, F-12, F-13, F-15 link cleanup (optional). F-14 clear (no change). F-16 positive (kept; hole closed by D-0029). Did not edit Lovelace or peer-owned files. Planning-only; no product code; no commit.

**Rationale:** Bohr ask to synthesizer; closes freeze blockers before any “interfaces frozen” claim.

## D-0036 — Lovelace final spot audit: accept; freeze blockers none

**Status:** active  
**Date:** 2026-07-27  
**Source:** `coordination/proposals/lovelace-final-audit.md` §16  

Lovelace final spot audit verdict: **accept**. Residuals R-01 / R-02 / R-03 closed on ledger (D-0023 / D-0017 / D-0021 / D-0026). Public docs unchanged this pass and clean. **Freeze blockers from Lovelace: none.** Planning-only (D-0001 / D-0024) remains until a human lifts it; this decision clears the independent audit gate, not product implementation.

**Rationale:** Independent red-team close-out of the synthesis surface; synthesizer stamps so the accept is auditable on the central ledger.

## D-0037 — First experiment: hard-constraint loss → false completion

**Status:** active  
**Date:** 2026-07-27  

Selected first experiment: hard-constraint loss during long multi-step agent work followed by false completion.

Design surface: `experiments/constraint-retention/`.

**Rationale:** Measurable, safe, locally reproducible, relevant to context/memory, reversible interventions.

## D-0038 — Bounded experiment-design phase

**Status:** active  
**Date:** 2026-07-27  

Bounded design phase for the constraint-retention experiment. Maximum: one concise proposal per specialist, one synthesized protocol, one red-team pass. No additional architecture work and no run implementation until the user approves the protocol.

**Ownership:** specialists write only `experiments/constraint-retention/proposals/<name>.md` and append to `coordination/agents/<name>.md`; Einstein alone owns `experiments/constraint-retention/PROTOCOL.md`; Lovelace alone owns `experiments/constraint-retention/AUDIT.md`; central `DECISIONS` / `CHANGELOG` remain steward or synthesizer-owned.

**Rationale:** Keep design thin and auditable before any run.

## D-0039 — Fresh experiment context; experiment-local agent logs

**Status:** active  
**Date:** 2026-07-27  
**Amends:** D-0038 ownership (agent-log path)

All experiment-design specialists were interrupted, their Cursor chats cleared, and assignments restarted from empty model context to prevent planning-phase anchoring.

Experiment agents log to fresh `experiments/constraint-retention/agents/<name>.md`, not historical `coordination/agents/` logs. Experiment agents may read only `experiments/constraint-retention/COORDINATION.md` and their fresh experiment-local files under `experiments/constraint-retention/`.

**Rationale:** Prevent planning-phase anchoring and keep the experiment audit surface self-contained.

## D-0040 — Constraint-retention protocol audited and accepted

**Status:** active  
**Date:** 2026-07-27  
**Sources:** `experiments/constraint-retention/PROTOCOL.md` §0; `experiments/constraint-retention/AUDIT.md` final delta section  

The constraint-retention experiment protocol was independently audited and accepted. All P0–P3 findings are closed. No implementation or runs yet.

**Rationale:** Central ledger stamp for Lovelace final-delta **accept** before any post-approval work.

## D-0041 — Next authorized experiment phase

**Status:** active  
**Date:** 2026-07-27  
**Aligns:** PROTOCOL §0 ladder 0.1→0.5  

Next authorized phase requires explicit user approval. After approval, only experiment-local prep seals may begin, followed by canary/rollback, then calibration, then scored stages. No product code outside the experiment surface. No commit unless separately asked.

**Rationale:** Keep the ordered exit ladder enforceable on the central ledger.

## D-0042 — Failure-to-intervention prototype authorized

**Status:** active  
**Date:** 2026-07-28  
**Source:** explicit user instruction, 2026-07-28

Build one small executable proof of the thesis at `prototypes/failure-to-intervention/`: reconstruct a synthetic duplicate-customer ops incident into deterministic SQLite state, run interventions through a constrained domain API, and score them with a hidden state-based verifier across one incident plus three counterfactuals. Stack pinned to TypeScript / Node / pnpm / SQLite / Zod / Vitest. Explicitly out of scope: web UI, MCP, auth, deployment, containers, model API calls, RL, plugin architecture, additional business domains, and any implementation of the dual-tier architecture from the retired `docs/DESIGN.md`.

Orchestrator wrote `prototypes/failure-to-intervention/PLAN.md` as the contract; subagents implement with single-writer file ownership; incremental commits are explicitly authorized for this work; root `README.md` may only gain a link to the prototype; the retired DESIGN.md stays untouched.

**Rationale:** Smallest runnable evidence that failure → stateful reconstruction → invariant evaluation → counterfactual variation distinguishes overfit from robust interventions, without opening the dual-tier build.

## D-0043 — Agent-in-the-loop rung: plan gated before build

**Status:** active  
**Date:** 2026-07-29  
**Source:** user planning session, 2026-07-29

The failure-to-intervention prototype may add a real model in the intervention slot, per `prototypes/failure-to-intervention/PLAN-agent.md`. Locked: Claude API with a pinned snapshot (key from environment, never committed); single-shot JSON-plan episodes (multi-turn deferred); k=10 runs per case with a five-way outcome taxonomy; transcripts as gitignored local evidence. The verifier, four case seeds, and failure_trace.json are frozen — agent work adds files only. Build begins only after explicit user sign-off on the plan; the live `pnpm demo:agent` run needs the user's key and a sub-$1 spend. Still out: MCP, UI, deployment, training, second models, local drivers.

**Rationale:** Prove the rig judges a stochastic agent fairly before investing in multi-turn or harder scenarios; keep the evaluation goalposts frozen so a pass means something.

## D-0044 — Agent rung signed off; behavioral audit made a first-class deliverable

**Status:** active  
**Date:** 2026-07-29  
**Source:** explicit user sign-off, 2026-07-29

User signed off on `PLAN-agent.md` with one amendment, adopted: the behavioral-audit writeup (`AUDIT.md`) is a required deliverable with a seven-point substance checklist — pre-registered predictions committed before the first live run (`PREDICTIONS.md`), full distributions, transcript-cited failure attribution, counterfactual-sensitivity analysis (does the model replicate `naiveIntervention`'s mistakes), environment-honesty accounting, honest negative results, and traceability of every number to `audit-data.json` or transcripts. Build is delegated to a user-spawned orchestrator agent whose subagents use Auto model selection only; same frozen-file and incremental-commit rules as round one.

**Rationale:** the writeup is the research output, not an afterthought — pre-registration is what separates a behavioral audit from a rationalization.
