# Current console QA results

The five fresh console QA receipts were collected against committed source
`b4501029a332d7675a12fbf84b00358230d3d154`. Independent read-only validation
found no actionable evidence mismatch. These receipts cover real scripted
workflows and inspection of two imported native trajectories, not new native
inference.

## Evidence

| QA phase | Collector checks | Screenshots | Original bytes |
| --- | ---: | ---: | ---: |
| Standard console | 35 | 16 | 5,005,722 |
| ATIF interchange | 13 | 5 | 1,128,013 |
| Access controls | 31 | 13 | 9,935,727 |
| Imported native ledger v2 | 25 | 11 | 2,156,417 |
| Imported native v1 | 25 | 11 | 2,984,375 |
| Total | 129 | 56 | 21,210,254 |

The original accounting includes 98 files, five reports and five videos.
Every original file's size and SHA256 was captured before validation and
rechecked unchanged afterward. This note and the
[independent validation sidecar](../artifacts/qa/20261010-current-final-validation-v1/independent-validation.json)
are additional publication files, outside those original counts and bytes.
An earlier failed preflight remains separate; it is not counted as successful
QA.

Original directories:

- [Standard console](../artifacts/qa/20261010-current-final-v1/ui-report.json)
- [ATIF](../artifacts/atif/qa/20261010-current-final-v1/ui-report.json)
- [Access](../artifacts/access-provisioning/qa/20261010-current-final-v1/ui-report.json)
- [Native ledger v2](../artifacts/access-ledger-study/qa/20261010-current-final-v2/ui-report.json)
- [Native v1](../artifacts/access-ledger-study/qa/20261010-current-final-v1/ui-report.json)

## Independent verification

All 34 fresh scripted episodes and both imported native episodes replayed
successfully with the compatible current runtime. All 36 generated ATIF
documents passed the actual pinned Harbor 0.24.0 `Trajectory` validator.
The canonical JSON-schema SHA256 was
`892a423ee9c710e8067740b36dd15c9de2f0157d05b6c1ea30acc25ff1c4da6c`;
this is a schema hash, not the hash of its Python source file.

All 26 downloaded JSONL files matched the real exporter byte for byte:
114 records and 7,333,290 bytes. Verification used the existing database
through a SQLite URI with `mode=ro` and `query_only=ON`, without invoking
the Store initializer or performing database writes. DPO lookup considered
all stored candidates, including older runs. The eight selected pairs came
from the fresh standard oracle and baseline runs.

The source audit checked 86 recorded hashes spanning 29 unique files against
the collection-revision Git blobs and current compatible bytes. The standard
console report does not contain a `controller_source` field. Its 16 fresh
scripted episodes independently record the collection SHA and
`implementation_dirty=false`; no absent report-level attestation is inferred.

The access operator JSONL contains all 16 full episodes, exactly matching
the stored/API episode values: 2,380,297 bytes. Operator evidence retains
snapshots and trusted grading for inspection. Downloaded trace and ATIF
interchange records exclude those private snapshots and grader fields.

## Training boundary

The real exporters verified 60 episode-format exclusions: 48 access
evaluation-only checks, six ATIF evaluation-only checks and six native
unsupported-protocol checks. Each count represents an episode tested against
one of SFT, DPO or grouped-rollout export, not a separate episode.

The standard 16 scripted episodes are not blanket-excluded from training
candidates. Captured exports contain 52 SFT decisions, eight DPO pairs and
eight grouped-rollout records. Grouped rollout data remains
`trainable=false`; it is not an on-policy GRPO training payload.

## Historical native imports

The two native records preserve their original collection provenance at
`cc2d4956c320867569e866bea3adbb53123a477f`. The
[three-file import receipt](../artifacts/access-ledger-study/20261010-import-v1/import-receipt.json),
original study wrapper lines, copied wrappers, database episode values and
cached API details match exactly. No inference or rollout was performed
during import or native UI QA.

| Protocol | Historical termination | Requests | Known input/output tokens |
| --- | --- | ---: | --- |
| Native v1 | Failed, timeout | 12 | 28,521 / 437, incomplete |
| Native ledger v2 | Completed, finished | 8 | 10,592 / 192, complete |

Historical elapsed durations remain 35.00361679203343 seconds for v1 and
4.476980958948843 seconds for v2. Import timestamps are not new execution
timestamps. A completed transport episode is not a business pass: these
selected historical trajectories remain failed business outcomes.

## Visual review and final state

Root independently reviewed all 56 screenshots through five contact sheets,
plus full CRM desktop/mobile screenshots. All five videos passed full
`ffmpeg -xerror` decode, and 15 early/middle/end frames were reviewed.
Videos are 1440 by 960 pixels; durations in table order are 5.36, 1.88, 5.40,
2.52 and 2.48 seconds. Gray letterboxing during mobile viewport captures is
intentional framing, not blank content. The validating worker did not repeat
browser collection or claim to perform root's visual inspection.

The final read-only database check found 11 runs, 68 episodes and no queued
or running jobs. Captured API health showed no active runs and paid calls
disabled. No browser errors were reported in the five receipts. These checks
do not claim cryptographic collection authenticity, hostile sandboxing,
representative model performance, cloud scaling or new training execution.

