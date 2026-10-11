# GitLab Incident Triage

The registered `gitlab-incident-triage` pack is an original, evaluation-only
fixture on pinned GitLab CE 19.4.1. It asks the ordinary developer account to
find one incident among identically titled issues, corroborate the public
on-call username, assign that account and add one severity label. Existing
labels, status, due date, descriptions, prior history and project access must
remain unchanged. Odd seeds start with both requested settings already correct;
leaving them unchanged is a legitimate successful outcome.
All seeds also include a non-target `INC-2026-0218` issue already assigned to
`casey-backup` with `incident` and `severity::3` labels; those unrelated joins and
labels must survive. The third incident has only the `incident` label and no
assignee. Seed modulo three rotates description order, not these case facts.

## Implemented Boundary

`gitlab_taskpacks.py` registers two frozen definitions. The runtime resolves a
trusted task ID before creating resources and retains that definition, task and
verifier image on its owned instance. Sealed artifact contents never choose
an exporter, fixture function or verifier. Family, case and seed define lineage;
code hashes separately identify the actual implementation. The API exposes both
public task manifests without protected expected IDs or sealed state.

The ordinary browser interface remains current AX node IDs, navigation, clicks,
fills, keys, scrolling and waits. The task-specific reference control reads only
those observations. It is a feasibility control, not a learned policy or a model
capability score. Screenshots and video remain operator evidence, not input to
the text model. No reset/admin API or grading state is supplied to the policy.

After browser closure and application-writer shutdown, the triage exporter adds
assignment joins, system-note metadata and label events to the existing selected
table projection. A separate network-disabled, read-only nonroot verifier checks
exact effects and preserves all prior rows in that projection. It does not call
the application, apply agent actions or trust a final answer. Assignment joins
have a composite user/issue identity, not an invented row ID.

Historical release `1.0.1` uses verifier `gitlab-triage-state-v2`. V1's reference failed at
30 actions and its later controls and model were unattempted. The new reference
recognizes actual singular/plural sidebar headings and ignores duplicate inline
heading text. The verifier permits a prior label event's null display reference
to populate with exactly `~` followed by that same immutable label ID, while
preserving every other attribute and row order. V1's original grades remain
unchanged. Actual V2 qualification also stopped: the reference opened the
assignee picker, mistook an unselected offered option for persisted assignment,
then made 21 rejected background clicks within its 30-action limit. Both control
grades remained zero, cleanup completed and the model slot was unattempted.
Independent sealed-state review reproduced those original grades without
replacement. Neither stopped cohort is a model capability result.

The separately declared V3 reference protocol distinguished an open picker,
observed selection and closed-field committed membership. It accepts only
current observed node IDs and stops after an uncertain-effect action instead of
repeating it. Its task release, fixture and grader were unchanged. No positive
qualification followed from those source repairs or mock tests.

Actual V3 at `62df4a994b1d5a3ded207ce957e594b927e05b94` also stopped after
two controls. The incomplete control completed with reward zero. The reference
persisted the exact on-call assignment, then failed with `provider_error` after
11 actions and zero invalid actions. GitLab closed the assignee picker immediately
after selection, with no Apply action, and the closed sidebar exposed only the
display name. The controller's Apply-only phase and username assumptions rejected
that observed transition. No severity operation occurred, so the original reward
zero remains correct. Already-correct, close-compatibility and model slots were
unattempted; there were no inference events. Both cleanups completed.

The generated assignment note also contradicts candidate certificate defaults:
its namespace is null, its projection has 28 fields rather than the candidate's
30, and its note/metadata timestamps follow the issue update.
Those are findings for a separately reviewed temporal and identity contract,
not permission to relax checks, add a tolerance or replace an original grade.
Independent read-only review reproduced both original grades and verified all
434 original files, 42 pinned source blobs, 98 journal records and 16 registered
media artifacts. GET-only console QA passed 38 checks with eleven desktop/mobile
screenshots and desktop playback; both videos decoded fully. Mobile playback
remains unqualified. Root separately confirmed idle admission, empty owned Docker
inventories and preservation of all prior operator rows and browser evidence.

## Versioned Commit Contract

Release `1.0.2` uses verifier `gitlab-triage-state-v3`, state schema
`world-engine-gitlab-triage-state-v2` and sealed schema
`world-engine-gitlab-triage-sealed-v2`. The V4 reference accepts immediate picker
closure only when closed-field membership and a new, structured public Activity
assignment row corroborate the selected username. A picker that stays open
requires observed selection and a scoped Apply action. Display-name-only
already-correct membership requires exact selected-username inspection and
nonmutating Escape dismissal. These observations guide navigation; they do not
replace isolated grading. Pending transitions permit at most five one-second
Wait decisions; that is not a wall-clock guarantee.

Each triage export records a six-digit UTC PostgreSQL `CURRENT_TIMESTAMP` in
the same read-only repeatable-read transaction as its selected rows. This is
the transaction-start time, not a maximum derived from mutation timestamps.
New certificates and changed target/project timestamps must fall between the
trusted baseline and final captures. Unchanged old project timestamps are not
forced into that interval. Note creation precedes its update and metadata
creation; assignment and labeling remain legal in either order. This avoids
treating the issue update as an upper bound for later certificate writes.
It assumes comparable local database clocks, not distributed-clock attestation.
[PostgreSQL date/time functions](https://www.postgresql.org/docs/current/functions-datetime.html).

New project-backed assignment notes require exactly the observed 28 fields,
with null `namespace_id`; `note_html` and `cached_markdown_version` are absent,
not optional null defaults. Actor, project and Issue identities remain exact,
and related joins and metadata retain their trusted namespace identities.
Prior records, permissions, defaults, counts and immutable fields still require
preservation. Historical schemas remain interpreted at their pinned source,
not silently accepted as the new contract.

**A complete positive triage outcome remains unqualified against a real reference
execution.** The partial assignment certificate is demonstrated below.
Its candidate exact note/metadata defaults fail closed. A legitimate GitLab
rendering/default mismatch stops qualification and preserves the rejected result;
any repair requires a new committed source/protocol and fresh collection. Mock
tests demonstrate the stated candidate contract, not actual application fidelity.
The selected tables do not certify every GitLab feature or side effect. The host
browser and operator-owned Docker setup are not a multi-tenant security sandbox.

Actual V4 at `a3aaa0f3f5f1412bd6989d35c61ba12c62c2d69c` stopped after
two controls. The incomplete control finished with reward zero. The reference
made 12 valid actions and zero invalid actions, then failed with `provider_error`
at the labels picker. Exact assignment and its isolated certificate passed;
severity was not added, so the original overall zero remains correct. Both
cleanups completed. Already-correct, close compatibility and the local-model
slot remain unattempted, with zero inference events.

The actual labels listbox has named Selected and All groups. Its selected
`incident` label appears in both with `selected=True`; the offered `severity::2`
option omits that attribute. The reference required an explicit boolean and
stopped before clicking it. This is a controller adaptation failure, not a model
capability result or permission to broadly reinterpret missing selection flags.

Independent read-only audits reproduced both original grades and all twelve
reference actions, verifying 439 original files, 42 source blobs, 103 journal
records and 17 registered media artifacts unchanged. The actual six-digit
database capture interval encloses the assignment note and linked metadata;
the project-backed note has the exact 28-field schema and null namespace.
That proves this partial certificate, not a successful full triage task.
GET-only console QA passed 39 checks with eleven desktop/mobile screenshots,
desktop playback and full decoding of both videos. Mobile playback remains
unqualified. Root verified idle admission, empty owned Docker inventories and
preservation of all fifteen prior browser rows and 256 browser evidence files.
Any repair requires a separately committed protocol and fresh control cohort;
no original grade or evidence is replaced.

The separately versioned V5 reference uses named Selected/All group membership
for the labels picker. It preserves prior closed label names, permits consistent
copies across groups and requires the exact expected selected inventory before
Apply and exact closed links afterward. Malformed flags, filtered or ambiguous
observations and premature closure fail closed. Missing flags are accepted only
for All options absent from the observed Selected group, not globally treated
as false. Task, fixture, grader and local-model contracts stay unchanged.
This is a bounded public-observation control, not authoritative grading or proof
of a complete hidden/virtualized inventory. Source tests alone do not establish
successful triage or admit a model run.

Actual V5 at `7033af7424bdd88eb6453efa17920aee1f3d3003` stopped after
374.0544615840772 seconds and two controls. Incomplete
`52254b64-f3c9-486d-ba21-d7362db0334f` finished with one valid action,
zero invalid actions, reward zero and completed cleanup. Reference
`03f20219-f9df-466b-9556-b33d8b3ce824` failed with `provider_error` after
13 valid actions, zero invalid actions, reward zero and completed cleanup.
Assignment, its exact certificate and preservation checks passed. Severity and
its certificate failed. Already-correct, closure compatibility and the model
remain unattempted with zero inference; no retries occurred.

The last action selected the current `severity::2` All option. The next public
observation marks that option `selected=True` and the dropdown title includes
both labels, but Selected still contains only the prior `incident` label.
V5 requires matching Selected/All positive memberships and rejects that draft
before Apply. The sealed state confirms no severity effect persisted, so the
original zero remains correct. This observation does not prove why Selected
differs, that waiting would refresh it, or that Apply would commit correctly.
It is a controller adaptation failure, not a model result or a grader defect.

Independent audits reproduced both original grades and all thirteen reference
actions, preserving 442 original files, 42 pinned source blobs, 108 journal
records and 18 registered media artifacts. All V1--V4 cohort bytes and eight
old operator seals remain unchanged. GET-only console QA passed 40 checks with
eleven desktop/mobile screenshots, advancing desktop playback and full decoding
of both videos. Mobile playback remains unqualified. Root verified idle
admission, empty owned Docker inventories and all seventeen prior browser rows
and 279 evidence files unchanged. Any correction requires a separately reviewed
source, protocol and fresh cohort; no original evidence or grade is replaced.

## Close-Task Compatibility

The close task is now release `1.0.3`: its fixture recipe moved into
`gitlab_close.py` and registered runtime dispatch changed. Its ordinary-comment
and closure semantics, export and `gitlab-state-v3` verifier are unchanged.
Historical `1.0.2` receipts remain intact and reproduce at their recorded source;
they are not reinterpreted as this release. Dispatch-only edits no longer change
the close recipe hash, but current controller source hashes still record them.

## Rights And Sources

Fixtures are original local evaluation material; no external benchmark tasks are
imported and these browser attempts are not training exports. GitLab CE's MIT
license does not waive separate image/dependency rights or rights in future user
data. The schema checks are based on pinned primary source:

- [Issue assignment model](https://gitlab.com/gitlab-org/gitlab-foss/-/blob/v19.4.1/app/models/issue_assignee.rb)
- [Label event model](https://gitlab.com/gitlab-org/gitlab-foss/-/blob/v19.4.1/app/models/resource_label_event.rb)
- [System assignment notes](https://gitlab.com/gitlab-org/gitlab-foss/-/blob/v19.4.1/app/services/system_notes/issuables_service.rb)
- [Project-backed Note model](https://gitlab.com/gitlab-org/gitlab-foss/-/blob/v19.4.1/app/models/note.rb)
- [Database structure](https://gitlab.com/gitlab-org/gitlab-foss/-/blob/v19.4.1/db/structure.sql)

See [qualification protocol](gitlab-triage-protocol.md). No control or model
collection is authorized merely by the presence of this guide.
