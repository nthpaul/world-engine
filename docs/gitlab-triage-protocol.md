# GitLab Triage Qualification Protocol V4

This is an integration qualification of two registered task packs, not training,
a population benchmark, a concurrency study or proof of full GitLab fidelity.
Default invocation prints the plan without Store, Docker, browser or model contact:

```sh
uv run python scripts/collect_gitlab_triage.py
```

V2 was a separately committed intervention after V1's changes-required reference
failed at 30 actions. The original V1 receipts and grades remain unchanged;
its already-correct, compatibility and model slots were unattempted. Reproduce
V1 at source `91641bc614fb567d176f10c01137a9bc36d0f851`, not this collector.
V2 changed the reference control to role-aware current-sidebar heading parsing,
including singular `Assignee` and duplicate inline heading text. The triage pack
is `1.0.1` with `gitlab-triage-state-v2`. Its verifier permits only the exact
prior label display-reference transition from null to that row's `~label_id`;
all other prior event attributes and identities remain exact. No old grade is
replaced. Reproduce V2 at source
`adda44a21151ed4d973415d875cbb07dbfa0becd`. Its reference stopped at 30 steps
with 21 invalid actions and reward zero; later slots were unattempted. These
results remain unchanged.

V3 changes only the triage reference controller. It recognizes the observed
Sidebar-local `combobox 'Search'` and `listbox 'Select assignee'`, instead of
interpreting unselected picker options as persisted assignment. It tracks the
active field through opening, searching, selecting and applying. An option
without a current observed node ID waits; an exact on-call option is selected
only inside that picker. Apply requires an observed boolean selection state,
and the closed field must confirm committed membership before the controller
opens another field or finishes. Picker options and descendants cannot prove
committed membership. Missing or ambiguous fields, pickers and Apply controls
fail closed. A recorded action result with `uncertain_effect=True` stops the
triage reference before another action; the generic runner, local model adapter
and close control are unchanged and retain their existing finalization behavior.

Actual V3 at `62df4a994b1d5a3ded207ce957e594b927e05b94` stopped after its
incomplete control and an eleven-action reference. The exact on-call assignment
persisted, but the picker closed without Apply and the closed field exposed a
display name. The reference failed before adding severity, so its original zero
grade remains correct. The already-correct, compatibility and model slots were
unattempted. The generated assignment note had 28 attributes, not the candidate
30, a null namespace and note/metadata timestamps after issue.updated_at.
Retain those original records; this collector does not replace their decisions.

V4 declares task `1.0.2`, grader `gitlab-triage-state-v3`, state and seal v2,
and reference `public-ax-triage-control-v4`. The controller handles observed
immediate commit and separately observed explicit Apply. Exact current picker
identity, closed target membership and target activity corroborate a new
assignment; display name alone and transient options are not completion proof.
Already-correct identity is inspected without toggling it. Pending transitions
allow at most five one-second waits, without repeating mutation clicks. Ambiguous
or uncertain effects stop the reference. Close and local-model protocols remain
unchanged. Real labels-picker behavior and successful full triage remain
unqualified until the fresh controls below pass.

The owned exporter records database CURRENT_TIMESTAMP inside each read-only,
repeatable-read snapshot transaction. Final capture follows browser closure and
writer shutdown. The baseline/final interval bounds new effects and changed
timestamps, not the issue's last update or a guessed tolerance. New assignment
notes require the exact 28-field project-note schema and null namespace; linked
metadata, joins and label effects retain exact trusted namespace/actor/target
identities. Within-row chronology and note-to-metadata ordering remain required;
assignment and label operations can occur in either order. Counts, immutable
rows, old history, permissions and unrelated records retain their exact checks.
Older schemas are rejected rather than silently reinterpreted. Mock tests and
offline decisions over prior AX do not establish application qualification.

Fixture distribution, permissions, seeds, order, budgets, model, generation
options and eligibility below remain unchanged. This is a new integration
qualification, not a matched capability comparison or retry within V3.

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
| Incomplete | Triage 1.0.2 | browser-baseline | 42 | 1 | 30s |
| Changes required | Triage 1.0.2 | browser-reference | 42 | 30 | 180s |
| Already correct | Triage 1.0.2 | browser-reference | 43 | 30 | 180s |
| Dispatch compatibility | Close 1.0.3 | browser-reference | 42 | 30 | 180s |
| Optional model | Triage 1.0.2 | local-browser | 42 | 30 | 600s |

Controls must finish, have zero invalid actions, complete cleanup and no pending
resource reconciliation. The incomplete control must fail the business outcome
with reward zero; the other three must pass every independent check and reward
one. The already-correct control must not create duplicate assignments, labels,
notes or events. If any control fails, stop and retain later slots as unattempted.
Both triage fixtures retain a distinct non-target issue assigned to the backup
account with a severity-three label, exercising preservation of nonempty joins
and label history. This is the original pre-collection distribution, not a later
repair selected from experimental outcomes.
The fixture distribution is unchanged from V1. The reference is now
`public-ax-triage-control-v4`; this does not change the local model's tool contract.
The collector verifies exactly one prepared policy identity for every slot after
retaining its terminal raw evidence. Controls require exact reference version,
baseline flag and training exclusion; the model requires the pinned digest,
protocol and generation options. A mismatched control cannot qualify the model gate.
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
