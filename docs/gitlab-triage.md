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

Release `1.0.1` uses verifier `gitlab-triage-state-v2`. V1's reference failed at
30 actions and its later controls and model were unattempted. The new reference
recognizes actual singular/plural sidebar headings and ignores duplicate inline
heading text. The verifier permits a prior label event's null display reference
to populate with exactly `~` followed by that same immutable label ID, while
preserving every other attribute and row order. V1's original grades remain
unchanged. Both fixes require the separately committed V2 qualification;
they are not evidence that the task or candidate verifier now succeeds.

The new verifier is **not yet qualified against a real reference execution**.
Its candidate exact note/metadata defaults fail closed. A legitimate GitLab
rendering/default mismatch stops qualification and preserves the rejected result;
any repair requires a new committed source/protocol and fresh collection. Mock
tests demonstrate the stated candidate contract, not actual application fidelity.
The selected tables do not certify every GitLab feature or side effect. The host
browser and operator-owned Docker setup are not a multi-tenant security sandbox.

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
- [Database structure](https://gitlab.com/gitlab-org/gitlab-foss/-/blob/v19.4.1/db/structure.sql)

See [qualification protocol](gitlab-triage-protocol.md). No control or model
collection is authorized merely by the presence of this guide.
