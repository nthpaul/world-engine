# Scripted Candidate Corpus

This is a separate candidate-data protocol, not a trainer or a model benchmark.
It schedules at most 128 deterministic scripted episodes: four current synthetic
worlds, seeds `50000..50015`, and oracle/baseline policies on each exact task.
There are no model, credential, network, Docker, browser or training calls.
The old three-world generator and all historical evaluation receipts are unchanged.

## Reviewed Plan

```sh
uv run python examples/scripted_candidate_corpus.py --plan
uv run pytest -q tests/test_scripted_candidate_corpus.py
```

Default invocation is plan-only and does not create a Store or provider. The plan
locks versions, all initial/world/grader fingerprints, scripted class source,
stable lineage splits and the protocol hash:
`d0b3a3c0c8ef9578f9d754ce137f4ca736db5f7a200d5acd22044907b2d49c2f`.
The 64 tasks have 51 train, 6 validation and 7 test lineages; both policies retain
the same split. These are seed holdouts within existing public families, not
new-family generalization. The seeds were checked against saved JSON/JSONL
receipts under `artifacts`, `examples/benchmark-results`, `examples/datasets`
and `examples/candidate-corpus`. Collection scans those declared roots again
before creating its private Store and refuses overlapping recorded seeds.
This is disjointness from the scanned receipts, not a claim about arbitrary
paths, other formats or global seed reuse.

Only after independent review and a clean source commit may an operator authorize:

```sh
uv run python examples/scripted_candidate_corpus.py --collect \
  --source-revision REVIEWED_FULL_40_CHARACTER_SHA \
  --output examples/candidate-corpus/NEW_RUN
```

This template has not been executed for this implementation. Output must be a
fresh directory; files/directories/live or dangling symlinks are refused before
source subprocesses or storage activity. Full runtime Python, dependency lock,
collector, tests and guide must be clean at the reviewed SHA; hashes and fixtures
are checked before each episode and source is checked at finalization.

## Storage And Failure Bounds

The private collector-only `QuotaStore` reuses the SDK Store without changing
shared runtime code. Inherited initialization is followed by confirmed DELETE
journaling, no WAL/SHM leftovers, and a 16 MiB SQLite page quota on every
connection. Budget partitions sum to 64 MiB: database 16, rollback journal 17,
raw failures 16, combined exports 14 and manifest 1. The journal allowance covers
single fixed Store transactions with a page-per-old-image journal and header
overhead; tests measure a transaction dirtying more than 14 MiB, rollback and
quota failure/reopen. Sampled journal size is not claimed as continuous telemetry.
This is a fixed trusted SQLite/scripted collector bound, not a hostile host sandbox.

Episodes are sequential, at most 20 decisions and 30 seconds each. Collection
has a 600-second cooperative aggregate budget with 30 seconds reserved for
finalization; it may stop before all slots. Eight MiB are reserved before another
episode for an unexpected full raw failure and the bounded manifest. No retries
or fallback policies are used. Built-in scripted providers have no prepare/close
resources; every Store connection commits/rolls back and closes through its
context manager. Interrupted run rows receive terminal interrupted status.

Returned episodes are committed in full to `candidates.sqlite3` before replay or
eligibility validation. Malformed or unpersistable serializable JSON envelopes
go to a bounded, fsynced `raw-failures.jsonl`. A non-JSON envelope, including NaN,
instead receives a generic diagnostic marker with `exact_envelope_preserved=false`;
it cannot be retained exactly as JSON. No object repr, invalid value or exception
detail is copied into that marker. The current slot becomes inconclusive, earlier
verified slots remain unchanged, later slots are unattempted. A cancelled current
episode or failed terminal run update also remains persisted but is marked
unverified/inconclusive and excluded from verified outcome and pair aggregates.
There is no duplicate
successful raw JSONL, SQLite copy or ATIF output. The operator database retains
protected grading/snapshots and all heldout/failing records; it is not trainer input.
Finalized transactions/fsync do not provide mid-episode process-crash durability.

## Export Meaning

New collection deliberately uses `evaluation_only=false` for candidate data.
It never rewrites an existing evaluation episode or its eligibility. The existing
exporter still requires the recorded `train` split, supported provider protocol,
successful cleanup and replay; oracle exports use `quality=passed`. Exact exporter
counts and all exclusion reasons are retained per world in `manifest.json`.

- `sft.jsonl` contains exact recorded per-decision controller context plus action,
  not hidden snapshots or grader rubric. Counts are measured after collection.
- `dpo.jsonl` requires comparable same-task/state/prompt/grader trajectories and
  a clean successful chosen trajectory with strictly higher reward. Its
  trajectory-message completion needs a trainer-specific adapter.
- `grouped-rollouts.jsonl` is raw comparable grouped interchange with
  `trainable=false`; mixed oracle/baseline policies are not an on-policy GRPO batch.

The maximum 51 preferences/groups is conditional on actual replay-valid,
clean/comparable controls and distinct trajectories. Missing token IDs, masks,
behavior logprobs and checkpoint evidence are not invented; trainer token count
is unknown (`null`), and no trainer is executed. The manifest distinguishes
observed business/clean outcomes, verified/inconclusive/unattempted slots, split
counts, source and artifact hashes, bounded database/exports and actual exclusions.
Per-world/policy outcomes and exact verified pair/comparability/trajectory counts
are separate from exported preference counts. Source is checked again after
export finalization; a stopped receipt is not an approved training candidate batch.
Replay proves trusted envelope/transition consistency, not learning or execution
authenticity. Generated candidates alone establish no improvement or generalization.
