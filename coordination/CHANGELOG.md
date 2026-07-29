# Changelog

Append-only record of coordination-surface and documentation changes.

## 2026-07-27 — Bootstrap steward: shared audit surface

### Created

- `SWARM.md` — agent coordination contract
- `coordination/DECISIONS.md` — decision log (D-0001, D-0002, D-0003)
- `coordination/CHANGELOG.md` — this file
- `coordination/agents/` — per-agent logs
- `coordination/agents/steward.md` — bootstrap steward agent log
- `coordination/proposals/` — per-agent proposal directory

### Deleted

- `README.md` — obsolete (D-0003)
- `docs/DESIGN.md` — obsolete (D-0003)
- `docs/` — empty directory removed after DESIGN.md deletion

## 2026-07-27 — Bootstrap steward: remove obsolete Cursor plan

### Deleted

- `.cursor/plans/world_engine_linear_project_b38a182c.plan.md` — obsolete planning document (D-0003)
- `.cursor/plans/` — empty directory removed after plan deletion

`.cursor/mcp.json` left unchanged.

## 2026-07-27 — Bootstrap steward: record D-0004 and D-0005

### Modified

- `coordination/DECISIONS.md` — appended D-0004 (eight specialist workstreams) and D-0005 (isolate concurrent writes)
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/steward.md` — recorded decision append

## 2026-07-27 — Bootstrap steward: record D-0006

### Modified

- `coordination/DECISIONS.md` — appended D-0006 (cross-cutting analyses before synthesis)
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/steward.md` — recorded decision append

## 2026-07-27 — Einstein synthesis: public planning surface

### Created

- `README.md` — mission, problem, users, closed loop, principles, wedge, TTVI/anti-metrics, current phase
- `ARCHITECTURE.md` — authoritative conceptual architecture (planes, artifact graph, stage contracts, identification, fidelity, certification, held-out/taint, trust boundaries, open-core boundary)
- `ROADMAP.md` — 0–6 week vertical slice + 2–6 month tracks; SG*/K* gates; non-goals; bottlenecks
- `RESEARCH.md` — ranked hypotheses H1–H15; experiments E1–E10; engineering vs research split; F1–F7 mapping
- `coordination/agents/einstein.md` — synthesis owner audit log

### Modified

- `coordination/DECISIONS.md` — appended D-0007…D-0024 (synthesis resolutions)
- `coordination/CHANGELOG.md` — this entry

### Not modified (per assignment)

- `.cursor/mcp.json`
- Specialist proposal files under `coordination/proposals/`
- Product / runtime code (none exists; none written)
- No git commit

## 2026-07-27 — Einstein: fold Feynman reward-lane soft residuals

### Modified

- `ARCHITECTURE.md` — §5.5 RewardValidationReport field freeze; H2 oracle/judges criterion-identity one-liner; §8.1 R6 null-result/top-k bridge; §10 cross-links
- `coordination/DECISIONS.md` — appended D-0025, D-0026, D-0027
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/einstein.md` — recorded Feynman ACCEPT + residual fold

### Not modified

- Specialist proposals (feynman filed §36 on own surface only)
- No product code; no commit; `.cursor/mcp.json` untouched

## 2026-07-27 — Einstein: §8.1 rank-universe clarify (Feynman §37)

### Modified

- `ARCHITECTURE.md` — §8.1 top-k rank universe = in-play rivals; exclude cleared (weakened|rejected ∧ null_result)
- `coordination/DECISIONS.md` — D-0026 clarify note (§32.2)
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/einstein.md` — recorded §37 ACCEPT + clarify

### Not modified

- No new D-id (compatible clarify only); no product code; no commit

## 2026-07-27 — Einstein: Lovelace final-audit required repairs

### Modified (synthesis-owned only)

- `README.md` — claim split: canary-affidavit provisional vs full loop proven (CAS EvidenceBundle + EvidenceReentryPlan); E6≠certified note
- `ARCHITECTURE.md` — §5.1 RedactionAttestation + DecisionTrace embedded; §5.2 catalog vs supporting aliases; §5.3 `gate.G*`; §5.5/D-0030 pointer; H2 grade×fidelity + Track-C judge packs; H7 CAS closure; §11 compensating rollback; §12 same-node sealed-fetch deny; enum scrub; ownership row
- `ROADMAP.md` — `gate.G*` / `split.S3-mini` / `breach.S*` cleanup; SG4/SG5 bars; weeks 2–6 spine vs non-blocking parallel; H7 CAS re-entry; underpowered week-6 language; Pasteur/Bohr links; E6 firewall
- `RESEARCH.md` — E6 GO ≠ production certified; week-6 provisional GO; E3/E7/E8 non-blocking; judge-pack Track C tense; `split.S3-mini`; CAS re-entry in E4
- `coordination/DECISIONS.md` — D-0028…D-0035; clarify/supersession notes on D-0009, D-0012, D-0015, D-0017, D-0021
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/einstein.md` — audit repair log

### Not modified

- `coordination/proposals/lovelace-final-audit.md` and all peer-owned proposal/log files
- `.cursor/mcp.json`
- No product code; no commit

### Repair coverage

Required: F-01, F-02, F-03, F-04, F-05, F-06, F-08. Optional: F-07, F-09, F-10, F-11, F-12, F-13, F-15 links. F-14 clear / F-16 kept.

## 2026-07-27 — Einstein: Lovelace R-01 / D-0023 spine clarify

### Modified

- `coordination/DECISIONS.md` — D-0023 Lovelace clarify (R-01): structure_only spine `E1→E2→E5→E4`; E6 reward_dependent-only / non-blocking
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/einstein.md` — recorded R-01 repair

### Not modified

- Peer/Lovelace proposal files; public docs already matched post F-09; no product code; no commit

## 2026-07-27 — Einstein: Lovelace re-audit §12 final ledger repairs (R-01/R-02/R-03)

### Source

- `coordination/proposals/lovelace-final-audit.md` §12 (re-audit residuals)
- Bohr `[ask]` to apply R-01 required + R-02/R-03 optional ledger-only

### Modified

- `coordination/DECISIONS.md`
  - **R-01:** D-0023 clarify/supersession strengthened — structure_only critical spine `E1→E2→E5→E4`; E6 non-blocking parallel + `reward_dependent` freeze switch only; never a prerequisite for green structure_only `DeployDecision`
  - **R-02:** D-0017 bold lead-in “Superseded for full-loop proof: see D-0029” + supersession note points at CAS/`EvidenceReentryPlan` (history preserved)
  - **R-03:** D-0021 clarify uses `gate.G*` (forbids `adopt.G*`); D-0026 clarify maps bare “S2/S3” → `breach.S2–S3` and `claim_grade` → `claim.G*`
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/einstein.md` — §12 repair log

### Not modified

- Public docs (`README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `RESEARCH.md`) — already aligned; consistency check: no edit required
- Lovelace / peer proposal files
- No product code; no `.cursor/mcp.json`; no commit

### Completion

Ready for final spot audit (ledger R-01/R-02/R-03 closed).

## 2026-07-27 — Einstein: Lovelace final spot audit accept (D-0036)

### Modified

- `coordination/DECISIONS.md` — appended D-0036 (Lovelace §16 accept; freeze blockers none)
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/einstein.md` — recorded final accept

### Not modified

- Public docs; Lovelace/peer files; no product code; no commit

## 2026-07-27 — Steward: final meta-language cleanup entry

### Summary

Lovelace, Einstein, Pasteur, and Hopper normalized wording in their owned audit and agent-log surfaces to the phrase **project-internal framing constraints**. Lovelace also updated its owned audit proposal. A repository markdown scan confirmed the obsolete meta-language is absent.

### Modified (this entry)

- `coordination/CHANGELOG.md` — this cleanup entry
- `coordination/agents/steward.md` — recorded cleanup

### Not modified

- Public planning docs
- Product code
- `.cursor/mcp.json`
- No commit

## 2026-07-27 — Steward: bootstrap constraint-retention experiment-design surface

### Created

- `experiments/constraint-retention/COORDINATION.md` — ownership and bounded-design rules
- `experiments/constraint-retention/proposals/` — specialist proposal directory

### Modified

- `coordination/DECISIONS.md` — appended D-0037 (first experiment selection) and D-0038 (bounded design phase)
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/steward.md` — recorded bootstrap

### Not created (owner-gated)

- `experiments/constraint-retention/PROTOCOL.md` — Einstein-owned
- `experiments/constraint-retention/AUDIT.md` — Lovelace-owned

### Not modified

- Public planning docs
- Product code
- Configuration (including `.cursor/mcp.json`)
- No commit

## 2026-07-27 — Steward: experiment-local agent logs and fresh-context restart (D-0039)

### Created

- `experiments/constraint-retention/agents/` — fresh experiment-local agent logs

### Modified

- `experiments/constraint-retention/COORDINATION.md` — agents log to `experiments/constraint-retention/agents/<name>.md`; D-0039 read/restart rules
- `coordination/DECISIONS.md` — appended D-0039
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/steward.md` — recorded administrative update

### Not modified

- Specialist proposal files
- Public planning docs
- Product code
- Configuration
- No commit

## 2026-07-27 — Steward: constraint-retention design close-out (D-0040, D-0041)

### Summary

Experiment-design phase closed on the central ledger. Clean-session reset (D-0039) produced eight specialist proposals, Einstein `PROTOCOL.md`, Lovelace `AUDIT.md`, repair passes, and final-delta **accept**. No implementation or runs. Next phase waits on explicit user approval, then experiment-local prep seals → canary/rollback → calibration → scored stages.

### Experiment-design surface (as closed)

**Bootstrap / ownership**

- `experiments/constraint-retention/COORDINATION.md` — D-0037/D-0038/D-0039 rules
- `experiments/constraint-retention/proposals/` — specialist designs
- `experiments/constraint-retention/agents/` — fresh experiment-local logs (D-0039)

**Eight proposals (design only)**

- `proposals/darwin.md`
- `proposals/faraday.md`
- `proposals/feynman.md`
- `proposals/hopper.md`
- `proposals/maxwell.md`
- `proposals/noether.md`
- `proposals/pasteur.md`
- `proposals/turing.md`

**Synthesis / audit**

- `PROTOCOL.md` — Einstein; §0 ordered exit ladder 0.1→0.5; repair map closes original P0–P3 + P1-6
- `AUDIT.md` — Lovelace; original audit → re-audit → final delta **accept**; all P0–P3 closed

**Repair / accept path**

- Required PROTOCOL patches for original P0/P1 findings
- Re-audit opened P1-6 (§0 circular with prep/canary); PROTOCOL §0 ladder fix
- Final delta audit: **accept** (`α_stage2 = 0.045`; standing bans kept)

### Modified (this entry)

- `coordination/DECISIONS.md` — appended D-0040 (protocol audited/accepted; no impl/runs) and D-0041 (next phase requires user approval; prep→canary→cal→scored; no out-of-surface product code; no commit unless asked)
- `coordination/CHANGELOG.md` — this entry
- `coordination/agents/steward.md` — recorded close-out

### Not modified

- Experiment `PROTOCOL.md`, `AUDIT.md`, proposals, or experiment-local agent logs
- Public planning docs
- Product code
- Configuration
- No commit
## 2026-07-28 — Orchestrator: failure-to-intervention prototype bootstrap (D-0042)

### Created

- `prototypes/failure-to-intervention/PLAN.md` — pinned contract: file tree, ownership, domain model, module signatures, invariants, acceptance criteria
- `coordination/agents/orchestrator.md` — orchestrator audit log

### Modified

- `coordination/DECISIONS.md` — appended D-0042 (prototype authorized)
- `coordination/CHANGELOG.md` — this entry

### Not modified

- `docs/DESIGN.md` (retired; pre-existing working-tree deletion left uncommitted, not staged)
- Public planning docs; `.cursor/mcp.json`

Commits explicitly authorized by the user for this work.
## 2026-07-28 — Orchestrator: failure-to-intervention prototype complete (D-0042)

### Created

- `prototypes/failure-to-intervention/` — executable proof: deterministic SQLite reconstruction from trace seeds, constrained domain API, hidden property-based verifier (seven invariants), naive vs robust interventions, `pnpm demo` matrix, 60-test Vitest suite, README + WALKTHROUGH
- `coordination/agents/{orchestrator,tesla,shannon,lamarr,hypatia,ramanujan}.md` — build, test, docs, red-team, and review audit logs

### Modified

- `README.md` — added Prototypes section linking the prototype (only authorized root change)
- `coordination/CHANGELOG.md` — this entry

### Verification

- Red team (hypatia) found two verifier hole classes; tesla patched verifier.ts; all 7 hole pins converted to permanent assertions
- Independent review (ramanujan): no blockers; one stale doc sentence fixed; two one-line hardenings applied
- Orchestrator personally ran `pnpm demo` (matrix matches PLAN), `pnpm test` (60/60), `pnpm typecheck` (clean) at every stage and at integration

Commits explicitly authorized; staged by explicit path so the pre-existing `docs/DESIGN.md` working-tree deletion stayed out of every commit.
## 2026-07-29 — Orchestrator: agent-rung plan drafted (D-0043)

### Created

- `prototypes/failure-to-intervention/PLAN-agent.md` — single-shot Claude driver in the intervention slot; frozen goalposts; k=10 pass-rate stats; transcript evidence chain; falsification rules

### Modified

- `coordination/DECISIONS.md` — appended D-0043
- `coordination/CHANGELOG.md` — this entry

### Status

- Plan-only. Build waits on user sign-off; live demo run needs the user's API key.
## 2026-07-29 — Orchestrator: agent rung signed off, audit deliverable amended (D-0044)

### Modified

- `prototypes/failure-to-intervention/PLAN-agent.md` — behavioral-audit section (seven substance requirements), PREDICTIONS.md/AUDIT.md/audit-report.ts added to file list, acceptance criterion 6
- `coordination/DECISIONS.md` — appended D-0044
- `coordination/CHANGELOG.md` — this entry

### Status

- Build delegated to a user-spawned kimi-k3 orchestrator with Auto-model subagents; orchestrator prompt drafted and handed to the user.
