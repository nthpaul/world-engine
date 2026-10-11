# Native Access Integration Study

This SDK-only collector evaluates one installed local model on the eight public
synthetic access-provisioning cases, seeds `0..7`, once each. It is not a paired
adapter comparison, population benchmark, training collection or vendor access
integration. Scripted oracle/baseline controls belong to a separate access receipt.
No inference is authorized merely by implementing or printing this plan.

## Plan First

```sh
uv run python examples/access_native_study.py --plan
uv run pytest -q tests/test_access_native_study.py
```

Default invocation is also plan-only: no provider construction, metadata request,
credentials, model calls, database, Docker or browser activity. The plan locks
world version `1.0.0`, all eight initial-state hashes, world/grader fingerprints,
native contract and a protocol SHA-256. Source changes require a separately
reviewed protocol; do not update a hash to make a failed check disappear.
The locked protocol SHA-256 is
`9aa85f8ab1d5bae48b1c9231d6649cf274d80377059ae6e0fd85c6ad6ff2fc76`.

After the collector, tests and protocol are reviewed and committed, an operator
may explicitly authorize this template with the resulting full lowercase SHA
and a **new** output directory:

```sh
uv run python examples/access_native_study.py --collect \
  --source-revision REVIEWED_FULL_40_CHARACTER_SHA \
  --output artifacts/access-native-study/NEW_RUN
```

This command has not been executed for this implementation. Existing directories,
files, live symlinks and dangling symlinks fail before source subprocesses or
provider preparation. The collector never overwrites earlier receipts.

## Locked Bounds

- Only `qwen3:8b`, installed digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Native Ollama tools only, one request per decision, no retries, fallback,
  downloads, cloud models or paid calls. Catalog/digest preparation precedes chat.
- `temperature=0`, `think=false`, `num_predict=512`, `num_ctx=8192`;
  eight episodes, at most twenty decisions and thirty-five seconds per episode.
- Concurrency one; six hundred seconds aggregate, including preparation and
  finalization. Fifteen seconds are reserved before starting another episode:
  three for cooperative provider close and the rest for bounded source checks
  and receipt finalization. Trusted SDK/host cooperation is required, not hard
  preemption of arbitrary Python or stalled filesystem operations.
- Sixty-four MiB total artifact cap; twenty-four MiB next-episode reservation
  plus one MiB report allowance. The capacity derivation covers this fixed world,
  capped recorder/wire contexts/actions and snapshots, not arbitrary environments.

The caller owns one prepared provider across sequential episodes and closes it in
`finally`, with a three-second cooperative timeout. Cleanup failure is reported;
it does not alter saved business outcomes or claim actual resource closure.

## Evidence And Interpretation

Only `evaluation-episodes.jsonl` and `report.json` are produced. Every returned
episode, including failures and malformed envelopes, is serialized, flushed and
fsynced **before** identity/replay validation or another request. A malformed or
mismatched current slot becomes inconclusive; earlier verified rows remain
unchanged, later slots stay unattempted. An exception without a final episode
gets a raw failure marker with unknown request accounting. Finalized records
retain exact bounded native provider events, usage completeness, provenance,
termination, invalid actions and hidden operator grading; none are trainer input.
This is finalized-episode durability, not mid-episode process-crash durability.

Full runtime Python files, dependency lock, collector, tests and protocol guide
must be clean at the reviewed revision. File hashes and fixtures are rechecked
between episodes and source is checked after cleanup. Whole-checkout dirty state
is recorded separately; unrelated documentation/artifacts do not imply a dirty
runtime. A final source failure stops the receipt, without rewriting raw records.

The report distinguishes business passes from clean passes, finalized/verified/
inconclusive/unattempted slots and complete versus known request counts. Unknown
usage remains unknown in per-episode recorded accounting. Replay verifies trusted
transition/envelope consistency, not signed execution authenticity or all model
weights. All wrappers and the report are explicitly `evaluation_only=true` and
`training_eligible=false`; native evidence is excluded from SFT/DPO/grouped RL
exports. This fixed eight-case exercise supports integration observations only,
not generalization, learning gains or an adapter advantage claim.
