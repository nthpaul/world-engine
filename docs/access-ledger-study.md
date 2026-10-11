# Native context comparison protocol

This collector compares two complete SDK contracts on eight repeated public synthetic access cases. It does not isolate deduplication, cache behavior, or a single prompt change. Native v1 sends the current observation and recent controller history. Ledger v2 retains the initial public context and every intermediate public observation, with a stable serialized prefix. Different context content is part of the comparison.

No results are claimed by this protocol. The original eight-episode native receipt is immutable and is not replaced by this collection. These seeds are declared repeats, not independent population samples or new task-family holdouts.

## Plan and collection

The default command constructs and checks local fixtures and prints the plan. It does not construct a provider, open a Store, inspect credentials, contact a daemon, or run inference.

```sh
uv run python examples/access_ledger_study.py --plan
```

Actual collection requires root review, a committed CI-green source revision, and explicit authorization. Supply that full lowercase SHA rather than a moving branch name. The output must be new; existing files, directories, and live or dangling symlinks are refused before provider contact. Never reuse a historical receipt path.

```sh
uv run python examples/access_ledger_study.py --collect \
  --source-revision <reviewed-full-40-character-sha> \
  --output artifacts/access-ledger-study/<new-run-name>
```

The collector source, its test and this protocol, all runtime Python sources, `pyproject.toml`, and `uv.lock` must match committed source. Their individual hashes are recorded. The full checkout dirty flag is separate from this scoped clean requirement. Source, fixtures, contracts, and prepared provider identity are checked before every episode and after provider cleanup. Any drift stops the collection without retrying or replacing earlier records.

## Locked cases and bounds

- World: `access-provisioning` version `1.0.0`; public seeds `0..7`, one episode per protocol per seed.
- Protocols: `ollama-tools-v1` and `ollama-tools-ledger-v2`. Both full contracts and hashes are in the plan.
- Order: even seeds run v1 then v2; odd seeds run v2 then v1. Concurrency is one.
- Model: existing `qwen3:8b`, catalog digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Options: temperature `0`, `think=false`, `num_predict=512`, `num_ctx=8192`, `keep_alive=5m`.
- Each episode: at most 20 decisions and 35 seconds. No retries, fallback, tuning, model pulls, remote providers, or paid calls.
- Overall: 660 seconds, including at most 30 seconds of preparation, cooperative 3-second cleanup per provider, and a 30-second finalization reserve. A new episode needs its full time reservation. Model chat attempts are capped at 320; a new episode requires 20 remaining attempts.
- Artifacts: 64 MiB total for the raw JSONL and report; 24 MiB reserved before each episode, 1 MiB reserved for the report. The fixed-world plan records the conservative derivation of the episode reservation.

Protocol SHA-256: `91e7782c305b5a66ec4ab8a5290b54850e102d232b045221480a048732ba49f6`.

The caller owns two prepared provider instances and closes each in `finally`. Timeouts bound cooperative async providers, not malicious extensions that block the event loop or suppress cancellation. A completed close is not an attestation that every external resource was released. Preparation records attempt/completion counts; metadata HTTP request counts remain unknown because that transport is not instrumented by the episode recorder. Installed catalog identity is not a signed claim about executed model weights.

## Evidence and analysis

`evaluation-episodes.jsonl` contains full returned envelopes, including finalized business failures and provider failures. The collector flushes and fsyncs each JSON record before replay or summary checks. This preserves the JSON values returned by rollout, not an original API wire representation. Transport bodies inside provider events retain their own byte hashes and completeness flags. Records are durable only after episode finalization, not during a process crash mid-episode.

A JSON-serializable but invalid envelope remains as exact returned JSON evidence and is marked inconclusive. If an envelope cannot serialize as JSON, or unexpectedly cannot fit the remaining artifact cap, the collector writes a bounded generic marker. It does not include object representations or exception details, and explicitly says the exact envelope was not preserved. The current slot is inconclusive; later slots are unattempted. No failed or malformed slot is silently removed. Cancellation retains a verified finalized record when replay accepts it, stops further episodes, and censors that pair from primary outcome comparisons.

`report.json` gives ordered slots, verified and inconclusive counts, cancelled and unattempted slots, status and termination counts, raw content hash, artifact byte totals, cleanup outcomes, and source evidence. No SQLite copy, ATIF duplicate, or trainer dataset is produced. All records are evaluation-only and `training_eligible=false`.

Primary comparisons use pairs with two replay-verified, comparable, noncancelled authoritative outcomes. Within-budget completed or failed episodes are retained as outcomes, including provider errors and timeouts. Pair identity checks include public initial observation, scenario, split, task, prompt, environment, and grader fingerprints. The report states the eligible denominator out of eight and lists missing-pair reasons.

For both business pass and clean success, report the four cells: both pass, v1 only, v2 only, neither pass. Clean success additionally requires completed status and no invalid tool actions. The paired point difference is `(v2-only - v1-only) / eligible pairs`; it is null when no pairs are eligible. A stopped collection is not approved as a complete comparison even when a descriptive verified prefix is available.

Resource totals are descriptive. Count every recorded chat attempt, including rejected or incomplete responses. Record observed request bytes, response body bytes or bounded prefixes, transport latency, request outcome categories, and reported token/inference duration totals with explicit known-count and completeness fields. Missing usage is unknown, not zero. A slot without a returned envelope makes aggregate attempt and byte accounting incomplete. Body bytes are not tokenizer counts, cache hits, or a guarantee of context-window consumption. Do not claim a model advantage or population-level success rate from this small fixed sample.

## Offline tests

```sh
uv run pytest tests/test_access_ledger_study.py
uv run ruff check examples/access_ledger_study.py tests/test_access_ledger_study.py
```

Tests fabricate provider records and mock semantic replay to exercise collector decisions. Runtime native protocol and independent transition replay tests remain separate. These tests make no model or network calls.
