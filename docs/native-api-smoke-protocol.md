# Native API integration smoke protocol

This is a predeclared two-attempt integration check, not a capability score,
paired performance study, admission study, or training dataset. Collection
requires separate authorization after review, commit, and green CI. No attempt
has been collected by publishing this protocol.

## Fixed workload

The ordered provider IDs are `local-tools`, then `local-tools-ledger`, selecting
the existing native v1 and native ledger v2 protocols. Each gets one
`refund-ops` version `1.1.2` episode at seed `54000`, twenty decisions,
35 seconds, concurrency one, evaluation-only true, and paid consent false.
There is no retry, prompt tuning, JSON fallback, or model download.

The only model is the already-installed public `qwen3:8b`, catalog digest
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
Native settings remain temperature zero, thinking disabled, 512 predicted
tokens, and context setting 8192. Retained bytes do not prove untruncated
tokenizer consumption, cache reuse, or authentic weight execution.

The source pins the fixture's initial snapshot and environment/grader hashes.
`plan().protocol_sha256` identifies all workload, endpoint, quota, and timing
constants. No shared provider, world, recorder, or API contract is changed.

## Preflight and ownership

Default execution prints the plan without source inspection, output creation,
API contact, or model contact. Python imports are ordinary local package imports.

Collection accepts only `http://127.0.0.1:8000`, with an optional final slash.
It rejects other hosts, ports, paths, credentials, queries, fragments, and
malformed values before activity. HTTP clients disable redirects and ambient
proxies. Public errors omit URLs, raw response text, and exception causes.

The output directory must be fresh; existing files, directories, and live or
dangling symlinks are refused before source or transport activity. The collector
requires matching full lowercase `--source-revision` and
`--api-startup-revision` values. The latter is an explicit operator attestation
that the server started from that source. Package version `0.1.0` is a readiness
check, not source authentication. The operator must restart the API at the
reviewed collection revision with paid calls disabled and no active jobs.

Source gates compare committed Git blobs with the entire `src/world_engine`
Python implementation, `pyproject.toml`, `uv.lock`, and these three collector,
test, and protocol files. That scope must be clean. Overall checkout dirtiness
is recorded separately and may change when out-of-scope artifacts are written.
The source is checked before submissions, after awaited preflight, and at the
end, including stopped prefixes.

Before each submission, health must report `status=ok`, version `0.1.0`,
`paid_calls_enabled=false`, and literal integer `active_runs=0`. The collector
reads only fixed-loopback Ollama `/api/tags` through the existing bounded
metadata helper. It selects the exact public model, valid local entry, and
expected digest. It retains only that selected projection and the attempt
counter, never the complete catalog, other model names, or malformed metadata
prefixes. The API-owned provider checks tool capability during preparation.
Client metadata attempts and server-owned preparation calls are different:
the latter are not counted by this collector or native request recorder.

There are at most two `POST /api/runs` requests, one for each fixed alias.
An ambiguous failed admission is never retried. If no canonical submitted UUID
is available, the collector cannot safely cancel that possibly accepted job.
It never guesses identities or cancels unrelated jobs. Concurrent operator
activity and a hostile daemon are outside this single-operator protocol.

## Evidence and limits

Polling uses bounded run-summary pages every 250 milliseconds, not repeated
large episode details. A terminal owned run gets one full detail request.
API bodies use identity-only raw streaming with a 256 KiB normal-response cap
and 15 MiB detail cap. Overflow retains only the bounded observed prefix,
marks it incomplete, and stops without parsing an action or claiming a full
body hash. Redirects and unsupported encoding are recorded failures.

Before JSON parsing or status validation, each API response body is saved in an
exclusive SHA256-named file and fsynced. Identical bodies share one file; every
response still has a distinct fsynced `api-responses.jsonl` reference with
method, local route, status, byte count, hash scope, and completeness. This raw
capture covers synthetic API health, summaries, admissions, owned details,
and cancellation only. Ollama metadata is deliberately omitted for privacy.
Headers and authorization values are not persisted.

Finalized episode envelopes are saved separately as one full evaluation-only,
training-ineligible JSONL wrapper per alias before replay or selection checks.
Each row records its `episode_file` path; each original file contains exactly
one wrapper line with an `episode` key for later read-only console inspection.
Python JSON parsing and canonical serialization retain integer versus float
types. These protected synthetic operator records may contain snapshots and
grader diagnostics; they are not training exports. Malformed details and
failed replay remain in raw evidence rather than being relabeled as success.

Original files have a 64 MiB aggregate quota. Each next run reserves 31 MiB,
with another 1 MiB for the report and 512 KiB for cancellation. Actual writes
check remaining bytes independently; each API call also reserves up to 2 KiB
for its journal entry. Cancellation consumes its cleanup reserve rather than
reserving it again, while preserving the report allowance. These are conservative reservations for
the fixed workflow, not a promise that a pathological response or large polling
history will permit both attempts. Quota exhaustion stops collection with
partial and unattempted slots preserved, without deleting earlier evidence.

The overall cooperative budget is 180 seconds. Work uses 170 seconds, reserving
ten for owned cancellation, source postchecks, and reporting. Requests have a
five-second timeout; cancellation is bounded to three seconds and attempted at
most once for each known owned run on stop. A cancellation response does not
prove daemon work ceased. Synchronous trusted source checks, blocking host I/O,
or controller termination are not hard-preempted. Reported elapsed time covers
preflight through cleanup/source postcheck, before the final report write.

Replay validates seeded transitions, authoritative outcomes, source/protocol
identity, and exact native records. The real exporter is checked for one
unsupported-native-protocol exclusion in each of SFT, DPO, and grouped formats,
without querying an alternative pool. Native counts and partial usage come from
bounded finalized request/outcome pairs, not server monkeypatches. API requests
are reported separately from native chat attempts. Missing or inconclusive
episodes cannot supply complete request accounting. Actual pinned Harbor
validation is a separate independent proof, not a collector dependency.

## Commands

Print the plan without contact:

```sh
uv run python examples/native_api_smoke.py
uv run pytest -q tests/test_native_api_smoke.py
```

Only after separate authorization, start the idle API from the approved
revision and collect into a new directory:

```sh
uv run python examples/native_api_smoke.py --collect \
  --source-revision REVIEWED_FULL_COMMIT_SHA \
  --api-startup-revision REVIEWED_FULL_COMMIT_SHA \
  --api http://127.0.0.1:8000 \
  --output artifacts/native-api-smoke/NEW_RUN
```

The terminal report distinguishes verified completed evidence, business pass,
timeout or failure, raw-saved inconclusive data, ambiguous admission, and
unattempted slots. Both planned outcomes remain visible. A passing model
attempt would establish one API integration execution under these bounds,
not a general quality, training, security, or throughput guarantee.
