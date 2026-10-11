# GitLab Triage Qualification Protocol

This is an integration qualification of two registered task packs, not training,
a population benchmark, a concurrency study or proof of full GitLab fidelity.
Default invocation prints the plan without Store, Docker, browser or model contact:

```sh
uv run python scripts/collect_gitlab_triage.py
```

Commit and review the runtime, collector, tests and this protocol first. Root must
restart the owned loopback API at that full revision and separately authorize the
local experiment. Use an explicit fresh directory; existing files, directories,
live/dangling symlinks and symlink parents are refused before network activity:

```sh
uv run python scripts/collect_gitlab_triage.py --collect \
  --source-revision FULL_REVIEWED_SHA --api-startup-revision FULL_REVIEWED_SHA \
  --output artifacts/gitlab-triage/NEW_QUALIFICATION
```

## Fixed Order And Gate

Every slot gets a new application database, accounts and browser context. Do not
retry, tune, replace a failed receipt, relabel an old close receipt or skip a gate.

| Slot | Task/version | Provider | Seed | Actions | Interaction timeout |
| --- | --- | --- | --- | --- | --- |
| Incomplete | Triage 1.0.0 | browser-baseline | 42 | 1 | 30s |
| Changes required | Triage 1.0.0 | browser-reference | 42 | 30 | 180s |
| Already correct | Triage 1.0.0 | browser-reference | 43 | 30 | 180s |
| Dispatch compatibility | Close 1.0.3 | browser-reference | 42 | 30 | 180s |
| Optional model | Triage 1.0.0 | local-browser | 42 | 30 | 600s |

Controls must finish, have zero invalid actions, complete cleanup and no pending
resource reconciliation. The incomplete control must fail the business outcome
with reward zero; the other three must pass every independent check and reward
one. The already-correct control must not create duplicate assignments, labels,
notes or events. If any control fails, stop and retain later slots as unattempted.
Both triage fixtures retain a distinct non-target issue assigned to the backup
account with a severity-three label, exercising preservation of nonempty joins
and label history. This is the original pre-collection distribution, not a later
repair selected from experimental outcomes.
The triage verifier's exact certificate defaults are provisional until the real
positive controls qualify. Do not soften a check and reuse the same collection.

The optional model requires a separately authorized `--include-model` flag after
all controls pass. It uses only already-installed public `qwen3:8b`, digest
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`,
and the current committed browser-native tool contract/options. The collector
records `ollama-browser-tools-v2`, temperature 0, think false, 512 output-token
limit and 16384 context setting (settings, not proof of exact consumed tokens).
It also
checks the selected local tag before submission, then preserves and checks the
actual prepared identity in the journal. That preflight is not an atomic lock
on the daemon: identity drift can invalidate a retained attempt, not justify
erasing it. No paid/cloud calls, downloads, fallback or model tuning are allowed.

## Evidence And Limits

Record all task, fixture, grader, recipe/export/build and controller hashes, stable
family/case/seed lineage and source rights. Exact source must match before each
submission and after finalization; API source comes from its captured provenance
plus the operator startup attestation, not a fabricated health revision field.
Preserve raw API bodies before parsing/acceptance, terminal journals, rejected
inference replies, screenshots/video, sealed hash, independent checks and cleanup.
Private sealed snapshots/expected IDs/admin credentials are not public artifacts.

The collector has a 6000s cooperative aggregate budget, 1600s per-attempt waiting
budget, bounded 30s HTTP requests and 640MiB total output checks, reserving 1MiB
for the stopped/completed report. API detail bodies are bounded to 16MiB and
artifact bodies to 128MiB; downloaded evidence is stored separately from API
response copies and both count toward the aggregate cap. Checkpoints are not a
hard filesystem or CPU quota. Exceeding a response cap may retain only prior
bounded evidence; do not claim an unavailable full response was preserved.
On timeout or uncertain submission, the collector does not create another
attempt or auto-cancel an unknown operation. The operator must reconcile the
existing attempt before further admission. All failures and unattempted slots
remain in the final report. Controls-only completion leaves the model explicitly
unattempted, not successful. These receipts remain evaluation-only/nontrainable.

Inspect real console/video at desktop, 390px and 360px after terminal collection.
No screenshot substitute or mock test establishes actual browser feasibility.
