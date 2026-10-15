# GitLab release readiness contract

`gitlab-release-readiness` is an original development task pack for the local
GitLab browser pilot. It requires the ordinary agent to read an authoritative
policy and release evidence before deciding what to do. It is evaluation-only,
not a training-data source. Physical qualification of this new pack is pending.

## Public workflow

In Release Operations, the agent finds a release issue by its description marker,
not by its title or creation order. It reads policy `READINESS-R1` and the matching
review and validation records posted by Administrator, username `root`.
Identically titled issues, existing history and evidence for another release must
remain unchanged.

The policy requires an approved review and passed validation. Both satisfied
means one ordinary ready decision note followed by closure. Pending validation
means one ordinary blocked decision note and an open issue. The instruction
defines the note grammar but does not supply the desired decision.

Seeds 42 and 43 select ready and blocked development instances. Other seeds repeat
these two rule cases and may rotate issue order. These are exposed fixtures, not
untouched holdouts, production workflow samples or independent release pipelines.
The evidence notes are synthetic records, not proof of a build or deployment.

The SDK example supports every registered pack. Its plan mode contacts no model
and creates no instance or output directory:

```sh
PYTHONPATH=src python examples/gitlab_browser.py --plan --task-id gitlab-release-readiness --seed 42 --provider browser-reference --max-steps 30 --timeout 180 --output /absolute/path/to/fresh-plan
```

Execution additionally requires committed unchanged source, cached application
images and the existing optional browser runtime. Reference controls test
feasibility, not learned-policy capability. Do not use a plan printout or mocked
dispatch as proof of physical qualification.

## Grading boundary

The controller captures trusted baseline and final state in a readonly database
transaction. Browser closure and video finalization precede writer quiescence,
sealing and a separate network-disabled verifier. The ordinary policy has no
access to reset credentials, sealed state or grading inputs.

The self-contained verifier validates the named policy and evidence against
trusted source identities. It derives readiness from baseline evidence, never
from the seed, case label, control output or the agent's claimed success. Every
required check must pass for binary reward one. An unchanged issue or `finish`
without the required note earns zero, including in the blocked case.

Checks cover exact ordinary note identity/attributes, disposition, timestamps,
closure certificates and preservation of prior rows across ten selected tables.
Ready requires one direct-close event after the note. Blocked requires no new
state event and unchanged business fields. Neither outcome permits editing old
notes, evidence, access, unrelated issues or project state. This projection does
not attest every GitLab table or feature.

## Verification status

Source tests exercise valid decisions and adversarial state mutations. They do
not prove application-side behavior, public author discoverability, screenshots,
video or model success. A separate fresh, pinned physical cohort must qualify
both decisions and incomplete/invalid controls before drawing those conclusions.
The note-only activity-field allowance is bounded but not yet physically proved.

The historical closure and incident-triage packs retain their original manifests
and asset bytes. Controller source changes acquire new fingerprints. Old
receipts still require their pinned revisions; no grade or media is replaced.

See [the browser architecture and limits](gitlab-browser.md),
[local lifecycle](gitlab-runtime.md), and [the original collection
protocol](gitlab-browser-protocol.md) for existing ownership and security rules.
This remains a trusted-operator, single-active-attempt local pilot, not a
multi-tenant sandbox or a learned-policy improvement claim.
