# ATIF Interchange

`world_engine.atif.export_episode(episode, run_id=None)` converts one full, replay-verified synthetic workflow episode into a text-only ATIF document. It adds no runtime dependency. It is not a Harbor execution adapter, Harbor trial result, training exporter, or trainer-ready rollout batch.

## Frozen Contract

The target is `ATIF-v1.8`, checked against Harbor's actual `Trajectory` Pydantic model at revision `09f5b964f8e5075f7e52fd08c9994dfc80ad5d24` (Harbor 0.24.0). Primary references are the [pinned RFC](https://github.com/harbor-framework/harbor/blob/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24/rfcs/0001-trajectory-format.md) and [reference model](https://github.com/harbor-framework/harbor/blob/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24/src/harbor/models/trajectories/trajectory.py). Harbor's [license](https://github.com/harbor-framework/harbor/blob/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24/LICENSE) is Apache 2.0. No upstream code or schema is vendored into the runtime.

Each recorded decision becomes one agent step with normalized action JSON, structured tool call, and linked observation containing the exact tool result and model-visible state. Tool-call IDs are explicitly export-derived, not original provider IDs. The first recorded controller input supplies the initial system/user steps. Every decision retains the controller's recorded `policy_input` in `extra`; it is not an attestation of a custom provider's internal transcript or HTTP formatting. These context snapshots are not presented as new chronological user turns. Agent-level model identity is the configured name; a recorded provider-reported model name overrides it at step level when available. A reported name does not independently verify model weights.

Scripted decisions set `llm_call_count: 0` and omit LLM metrics. Built-in HTTP decisions set it to one and map only observed input/output tokens. Custom provider inference counts remain unspecified. Token totals cover recorded successful provider decisions only: requests that failed before a decision are not captured by the engine. Model identity, digest, usage, state hashes, original source fingerprints, seed, split, invalid actions, and faithful termination/outcome are retained. Protected grader check details, private expected fixtures, and snapshots are omitted. Empty traces contain only the recorded initial observation, not an invented model call.

Per-step wall timestamps, raw response byte fidelity, costs, reasoning, token IDs, and logprobs are unavailable and omitted. Episode `created_at` is retained as `recorded_at`, not relabeled as a step timestamp. The document preserves the recorded boolean `evaluation_only` and always sets `training_eligible: false`. Generic ATIF consumers must honor those custom eligibility flags; schema validation alone cannot enforce a downstream consumer's training policy. This output is operator interchange, not automatic training consent. Terminal-Bench data is not imported by this example.

## Export Existing Episodes

```sh
uv run python examples/export_atif.py
```

This reads existing `examples/benchmark-results/local-model-traces.jsonl`, performs no model calls, and writes only `artifacts/atif`. It rejects replay-inconsistent source episodes and inconsistent evaluation wrappers. Other full synthetic episode JSONL files can be supplied with `--source`; raw training trace exports omit fields needed for full replay and are not valid inputs.

The console's Harbor ATIF option uses the existing export controls. Batch HTTP/CLI downloads are JSONL: each line is a separate valid ATIF document, not a single Harbor trajectory JSON file. Split lines into individual JSON documents before using upstream tools that accept only one trajectory. The standalone example already writes individual JSON files.

## Validate With Upstream

Fetch and install the pinned upstream source into a separate temporary target, without installing Harbor into the application's environment or pulling its runtime dependencies:

```sh
curl -fsSL https://codeload.github.com/harbor-framework/harbor/tar.gz/09f5b964f8e5075f7e52fd08c9994dfc80ad5d24 -o /tmp/world-engine-harbor-atif.tar.gz
tar -xzf /tmp/world-engine-harbor-atif.tar.gz -C /tmp
uv pip install --no-deps --target /tmp/world-engine-atif-upstream /tmp/harbor-09f5b964f8e5075f7e52fd08c9994dfc80ad5d24
PYTHONPATH=/tmp/world-engine-atif-upstream WORLD_ENGINE_ATIF_VALIDATE_UPSTREAM=1 uv run pytest tests/test_atif.py
PYTHONPATH=/tmp/world-engine-atif-upstream uv run python examples/export_atif.py --validate-upstream
```

The integration test calls upstream `Trajectory.model_validate`, checks the reference schema fingerprint, and exercises successful, invalid-action, and maximum-step episodes. The example checks that fingerprint before validating every exported document against the actual model. It saves `artifacts/atif/validation-receipt.json` with source/output hashes, upstream revision, model class, schema hash, Pydantic version, executed command/Python path, and actual validation result. `exporter_source` separately captures the exact adapter and collector file SHA256 values, current Git HEAD, and dirty status scoped to those two files. Missing Git information is recorded as unknown, not clean. Collect the final receipt after committing the exporter sources. Original episode provenance describes episode collection, not the later ATIF conversion.

The upstream schema hash is generated with the recorded Pydantic version; a future dependency/schema change requires explicit revalidation rather than a compatibility assumption. Default unit tests do not fetch or require Harbor.
