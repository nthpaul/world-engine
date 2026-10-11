# ATIF Interchange

`world_engine.atif.export_episode(episode, run_id=None)` converts one full, replay-verified synthetic workflow episode into a text-only ATIF document. It adds no runtime dependency. It is not a Harbor execution adapter, Harbor trial result, training exporter, or trainer-ready rollout batch.

## Frozen Contract

The target is `ATIF-v1.8`, checked against Harbor's actual `Trajectory` Pydantic model at revision `09f5b964f8e5075f7e52fd08c9994dfc80ad5d24` (Harbor 0.24.0). Primary references are the [pinned RFC](https://github.com/harbor-framework/harbor/blob/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24/rfcs/0001-trajectory-format.md) and [reference model](https://github.com/harbor-framework/harbor/blob/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24/src/harbor/models/trajectories/trajectory.py). Harbor's [license](https://github.com/harbor-framework/harbor/blob/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24/LICENSE) is Apache 2.0. No upstream code or schema is vendored into the runtime.

Each recorded decision becomes one agent step with normalized action JSON, structured tool call, and linked observation containing the exact tool result and model-visible state. Tool-call IDs are explicitly export-derived, not original provider IDs. The first recorded controller input supplies the initial system/user steps. Every decision retains the controller's recorded `policy_input` in `extra`; it is not an attestation of a custom provider's internal transcript or HTTP formatting. These context snapshots are not presented as new chronological user turns. Agent-level model identity is the configured name; a recorded provider-reported model name overrides it at step level when available. A reported name does not independently verify model weights.

Scripted decisions set `llm_call_count: 0` and omit LLM metrics. Built-in HTTP decisions set it to one and map only observed input/output tokens. Custom provider inference counts remain unspecified. Standard ATIF token totals cover executed provider decisions, including environment-denied actions, not every attempted request. The default unrecorded HTTP mode does not retain failed-call bodies. Native and recorded-JSON modes instead preserve paired request/response events and reported attempt usage in `extra`; completeness flags distinguish known sums from complete totals. Neither wire evidence nor a reported token count reconstructs sampled IDs or probabilities.

Model identity, digest, usage, state hashes, original source fingerprints, seed, split, invalid actions and faithful termination/outcome are retained. Protected grader checks, private expected fixtures and snapshots are omitted. Empty traces contain only the initial observation, not an invented model call. Episode `created_at` is retained as `recorded_at`, not relabeled as a step timestamp. Normalized steps do not invent timestamps, reasoning, costs, token IDs or logprobs. Recorded evidence modes retain exact bounded application bytes and collector-observed timing separately in `extra`, with observed-prefix declarations when incomplete. This is not a chronological native-provider transcript.

The document preserves the recorded boolean `evaluation_only` and always sets `training_eligible: false`. Generic ATIF consumers must honor these custom flags; schema validation cannot enforce a downstream training policy. This is operator interchange, not automatic training consent. Terminal-Bench data is not imported by this example.

## Export Existing Episodes

```sh
uv run python examples/export_atif.py \
  --source /path/to/current-full-episodes.jsonl \
  --output artifacts/atif/NEW_RUN
```

This performs no model calls. Supply full synthetic episode JSONL whose implementation fingerprints match the active source. The current example requires a fresh explicit `--output`, reserves a mode-0700 directory before upstream imports/source work, and creates files exclusively. Existing directories, files and live/dangling symlinks are refused; prior exports/receipts are never pruned. Replace `NEW_RUN` with an unused name.

The legacy default input is `examples/benchmark-results/local-model-traces.jsonl`, a historical foundation receipt. It does not replay against today's revised worlds. Use a compatible pinned historical exporter/source to reproduce historical conversion, or explicit current-source input for the current command. The example rejects replay-inconsistent episodes and inconsistent evaluation wrappers. Raw training trace exports omit fields needed for full replay and are not valid inputs. It accepts one to 100 full episodes, not an arbitrary complete 128-slot study journal; failed-attempt records without an episode are not exportable trajectories.

The console's Harbor ATIF option uses the existing export controls. Batch HTTP/CLI downloads are JSONL: each line is a separate valid ATIF document, not a single Harbor trajectory JSON file. Split lines into individual JSON documents before using upstream tools that accept only one trajectory. The standalone example already writes individual JSON files.

## Validate With Upstream

Fetch and install the pinned upstream source into a separate temporary target, without installing Harbor into the application's environment or pulling its runtime dependencies:

```sh
curl -fsSL https://codeload.github.com/harbor-framework/harbor/tar.gz/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24 -o /tmp/world-engine-harbor-atif.tar.gz
tar -xzf /tmp/world-engine-harbor-atif.tar.gz -C /tmp
uv pip install --no-deps --target /tmp/world-engine-atif-upstream /tmp/harbor-09f5b964f8e5075f7e52fd08c9994dfc80ad5d24
PYTHONPATH=/tmp/world-engine-atif-upstream WORLD_ENGINE_ATIF_VALIDATE_UPSTREAM=1 uv run pytest tests/test_atif.py
PYTHONPATH=/tmp/world-engine-atif-upstream uv run python examples/export_atif.py \
  --source /path/to/current-full-episodes.jsonl \
  --output artifacts/atif/NEW_VALIDATED_RUN --validate-upstream
```

The integration test calls upstream `Trajectory.model_validate`, checks the reference schema fingerprint, and exercises successful, invalid-action and maximum-step episodes. The example checks that fingerprint before validating every exported document against the actual model. It saves `validation-receipt.json` inside the fresh output, with source/output hashes, upstream revision, model class, schema hash, Pydantic version, command/Python path and actual validation result. `exporter_source` separately captures adapter/collector SHA256 values, current Git HEAD and their scoped dirty status. Missing Git information is unknown, not clean. Collect final evidence after committing exporter source. Original episode provenance describes episode collection, not later conversion. The new output-preservation source change is not a new export or upstream-validation result.

The upstream schema hash is generated with the recorded Pydantic version; a future dependency/schema change requires explicit revalidation rather than a compatibility assumption. Default unit tests do not fetch or require Harbor.

## Current Recorded Validation

The finalized access controls (64 episodes), protocol-v3 workflow variants (128), four-world benchmark (2,160), native access study (eight), and access UI v2 (sixteen) have separate independent validation receipts. These are additional dated collections, not new outcomes retrofitted into foundation or matched-study artifacts. UI v2's sixteen downloaded ATIF documents were checked against actual Harbor 0.24.0 with canonical schema hash `892a423ee9c710e8067740b36dd15c9de2f0157d05b6c1ea30acc25ff1c4da6c`; all ten UI downloads reproduced byte-for-byte. See [UI validation](../artifacts/access-provisioning/20261010-ui-v2/independent-validation.json) and [native access diagnosis](access-native-results.md). Schema conformance is not execution authenticity, Harbor job integration or training permission.

The later [scripted candidate corpus](../artifacts/candidate-corpus/20261010-v1/manifest.json) has 128 independently replayed episodes, each checked against actual Harbor 0.24.0. Unlike evaluation-only receipts, its train-split scripted records can supply candidate exports under existing replay/quality gates: 397 SFT decisions, 51 DPO pairs and 51 mixed-policy nontrainable groups. Thirteen heldout reference cases are excluded per format. ATIF validation does not make those transformed completions trainer-ready.

SDK integration at `d71a05d` permits explicit native-ledger v2 while default v1 stays unchanged. Both protocols remain operator-only and training-ineligible. The newer provider fingerprints require pinned source for older native receipts. The [later eight-pair access comparison](../artifacts/access-ledger-study/20261010-v1/report.json) at `cc2d4956` passed replay and actual Harbor checks for all sixteen episodes, but neither protocol passed a business task. Schema validity is not task correctness or trainer readiness.

The [current five-phase console proof](../artifacts/qa/20261010-current-final-validation-v1/independent-validation.json)
at `b4501029` validates 34 new scripted episodes and two unchanged native imports
against actual Harbor 0.24.0, with 26 byte-exact downloads. Native API/console
aliases are evaluation-only entrypoints, not permission to train on interchange
or a new model-execution claim. Imported provenance and counters remain those
of the original `cc2d4956` collection.

The [post-change CPU profile](../artifacts/profiling/20261010-v2/independent-validation.json)
checks all 192 saved scripted episodes against the same actual schema. The
[model admission study](model-concurrency-study-results.md) separately checks
all 32 native episodes at `1d9f2315`; all 96 SFT/DPO/grouped exclusions passed,
without visiting alternative pools. Eight task identities repeat four times,
not 32 independent tasks. Neither document shape, exact wire bytes nor replay
supplies sampled token IDs, masks or old-policy probabilities.

The separate [actual native API smoke](native-api-smoke-results.md) at
`8b82c7aa` supplies two original model episodes on one refund task; both replay
and validate against actual Harbor. Source51 read-only UI inspection reproduces
ten downloads exactly: two operator/two ATIF rows and six empty native training
files. No new episode, import or inference occurs during that inspection.
These two ATIF checks are not new independent task samples, successful training
or native Harbor job execution.
