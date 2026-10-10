# Historical planning README

Archived 2026-10-10. This planning document records an earlier scope. Its relative links and phase statements are historical, and some referenced files were never present in this checkout. Use the root README and current operations guide for the executable rebuild.

Open infrastructure that turns **production agent failures** into **validated, guarded improvements**.

This repository is in a **planning-only** phase (see [ARCHITECTURE.md](ARCHITECTURE.md), [ROADMAP.md](ROADMAP.md), [RESEARCH.md](RESEARCH.md)). No product runtime is claimed yet. Coordination audit surface: [`SWARM.md`](SWARM.md), [`coordination/`](coordination/).

---

## Mission

Give builders and reliability operators a closed path from *what broke in production* to *a change that earned the right to ship*—or an explicit, auditable refuse.

Improvement is a **control problem**, not a dataset bake-off. The scarce asset is contracts, validators, and gate discipline—not a proprietary weight dump.

---

## Precise problem

Deployed agents fail in ways offline evals miss. Operators see incidents, regressions, and silent drift, but the path from evidence to a safe update is broken in four places:

1. Evidence stays thin or untyped—logs do not become causal explanations.
2. Diagnosis does not yield replayable counterfactual tasks.
3. Rewards and updates go unvalidated—patches can optimize the wrong signal or memorize the incident.
4. Deployment lacks a held-out and canary gate—changes ship without adversarial checks or evidence re-entry.

**One sentence:** Build a model- and harness-agnostic closed loop that turns production failures into causally grounded counterfactual tasks, adversarially validated rewards, and guarded updates—then proves those updates improve held-out behavior before they touch live traffic.

---

## Users

| Persona | Role |
|---------|------|
| **Agent builder** (primary) | Ships tools, harness, prompts, memory, optional post-training. Needs reproducible failures and measurable lifts with low lock-in. |
| **Reliability / eval operator** (primary) | Owns quality gates, incidents, release criteria. Needs typed evidence, pass/fail gates, rollback. |
| **Research contributor** (secondary) | Extends environments, diagnosers, probes, update adapters behind stable contracts. |
| **Platform integrator** (secondary) | Connects an existing harness, telemetry store, and deploy path via thin adapters. |

End consumers of the agent’s output are beneficiaries, not direct users of this system.

---

## Full closed loop

```
production evidence
        ↓
causal diagnosis
        ↓
counterfactual environments & tasks
        ↓
adversarial reward validation
        ↓
update (choose + apply intervention)
        ↓
held-out simulation evaluation
        ↓
guarded deployment
        ↓
new production evidence ──┘
```

Each stage’s output must be a valid input to the next under distribution shift and Goodhart pressure. Skipping a stage requires a ledgered break-glass exception and taints the promote path.

**Reject, abstain, and rollback are successful outcomes** when warranted. Silent hope is not.

---

## Differentiating principles

1. **Evidence before update** — no shippable change without evidence → diagnosis → counterfactual lineage.
2. **Counterfactuals over anecdotes** — incidents become environments/tasks that can fail again under variation.
3. **Causal honesty** — constructed elicitation ≠ independent recovery; claim grades rise only with identification plans (primary + placebo + rivals).
4. **Reward is guilty until validated** — every promote path carries a reward-validation artifact (`certified` or explicit `not_applicable`).
5. **Held-out is sacred** — sealed access classes and taint closure are architectural invariants, not honor systems.
6. **Least risk that works** — prefer reversible structure-only interventions; every applied change has a rollback spec.
7. **Guarded by default** — canary, kill criteria, evidence re-entry; docs-only deploy templates are not loop proof.
8. **Local / sovereign by default** — data stays on the operator’s machine; portable, digest-addressed artifacts for export.
9. **Agnostic at the seams** — models, harnesses, and vendors plug in behind contracts; core never hard-depends on one stack.
10. **Falsifiability** — the thesis states how it dies; anti-metrics catch self-deception.

---

## First open-source wedge

**Name:** Failure-class canary loop (one harness, one class, one reversible update).

Prove **loop closure**, not artifact volume:

1. Ingest recorded/redacted evidence for one recurring failure class from **one reference harness**.
2. Emit a human-legible diagnosis with cited spans.
3. Compile a runnable counterfactual family with **deterministic replay**, contrast set (causal flip + placebo + rivals when claiming ID), and **pre-update fail attestation**.
4. Attach adversarial reward validation (planted-bug catch required when claiming adversarial completeness; `structure_only` may emit `not_applicable`).
5. Apply one **reversible non-weight** update (`structure_only`: prompt / tool policy / diagnosis-justified memory).
6. Run **sealed held-out** evaluation (target class + adjacent regress).
7. Reach a **guarded deployment decision** (ship *or* rollback) and close H7: post-canary episodes CAS-put as redacted `EvidenceBundle`s under the same failure class, with `EvidenceReentryPlan` outcome recorded.

**Not in the wedge:** multi-tenant control plane, weight training, pack marketplaces, N≥50 vanity suites, second harness, hosted SKUs.

**Claim split (marketing forbid):**

| Claim | Allowed when |
|-------|----------------|
| Harness smoke | Offline pack runs; artifacts emit |
| Canary-affidavit provisional | Partner/local canary with kill criteria + public or shared **hash list**, but post-canary bodies not yet CAS-ingested |
| Full loop proven | Deploy decision **and** post-canary episodes ingested as redacted `EvidenceBundle` digests in a permitted local or tenant-private CAS **and** `EvidenceReentryPlan` outcome recorded (partner canary OK; YAML-only / hash-list-only **not**). Public disclosure of sensitive content is not required. |
| Safe to optimize (`reward_dependent`) | Live unexpired `certified` certificate — **not** implied by wedge success or by E6 lab GO |

---

## North-star and anti-metrics

### North-star

**TTVI — time-to-validated-improvement:** median wall time from first detection of a production failure class to a held-out-gated update that shows meaningful lift on that class (and no material regress on the sealed suite) under guarded deploy—**or** an explicit lineage-complete reject.

Supporting: failure-class coverage, gate precision (held-out pass ↔ canary move), loop completion rate (deploy-or-reject, no silent abandonment).

### Anti-metrics (drive these down)

| Anti-metric | Why toxic |
|-------------|-----------|
| Offline-only win rate | Lift on tasks derived from the same incidents used to fit |
| Vacuous adversarial pass | “Search found none” without planted-bug catch |
| Suite contamination | Held-out leakage into fit data |
| Silent patch rate | Changes without evidence chain |
| Canary revert without lineage | Gates are theater |
| Vendor-coupled core PRs | Agnostic seams eroding |
| Task-count vanity | Volume without reproduction attestation |

---

## Prototypes

- [`prototypes/failure-to-intervention/`](prototypes/failure-to-intervention/) — first executable slice of the loop: a synthetic duplicate-customer ops incident reconstructed as deterministic SQLite state, scored by business invariants, varied across three counterfactuals, and used to separate an overfit fix from a robust one. Run `pnpm demo` inside the directory for the result matrix.

---

## Current phase

| Item | Status |
|------|--------|
| Phase | **Planning only** — no product code |
| Doctrine | Synthesized from specialist proposals (see `coordination/DECISIONS.md`) |
| Next | Freeze contracts → thin vertical slice per [ROADMAP.md](ROADMAP.md) |
| Research kill chain | [RESEARCH.md](RESEARCH.md) |
| Architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |

**Thesis falsifiers (kill or narrow):** systematic failures too rare; diagnosis not operationalizable; rewards unvalidatable; held-out never transfers to canary; agnostic seams impossible; TTVI no better (and no safer) than baseline ops; guarded deploy unavailable. Details in RESEARCH.md and `coordination/DECISIONS.md`.
