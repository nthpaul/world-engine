# Recorded JSON Provider

`HTTPProvider(config, record_calls=True)` is an explicit, local-only SDK option.
The API, CLI, provider registry and console still use the default JSON provider.
No inference is performed by constructing a provider. A caller must prepare it
before a local decision; `RunManager` performs preflight for its own providers.

## SDK Use

This example performs local inference when executed. It requires an already
installed model and never pulls models or enables cloud or paid calls.

```python
from world_engine.models import RunConfig
from world_engine.providers import HTTPProvider
from world_engine.rollout import rollout

config = RunConfig(
    environment_id="crm-merge", provider_id="local", model="qwen3:8b",
    seed=42, max_steps=20, timeout_seconds=120, evaluation_only=True,
)
provider = HTTPProvider(config, record_calls=True)
try:
    await provider.prepare()
    episode = await rollout(config, 0, provider)
finally:
    await provider.close()
```

Direct recorded decisions outside a rollout fail before sending a request.
Preflight checks an exact installed model name and a 64-character lowercase
hexadecimal catalog digest, rejects cloud names and catalog/show remote markers,
requires `completion` capability, and records a bounded reported daemon version.
Changing the selected model invalidates preflight. These checks do not attest
the daemon's execution or guarantee frozen weights.

## Protocol

The frozen protocol identifier is `ollama-json-evidence-v1`. Each decision uses
the existing JSON policy: one system message plus current public observation and
normalized action/result history. The request's `format` is the actual Pydantic
`Action` schema. The local options remain temperature 0, 512 predicted tokens,
8192 context tokens, `think=false`, `stream=false`, and `keep_alive="5m"`.
There is no retry, fallback, native tool call, synthesized conversation turn or
automatic model download.
An accepted local response must report exactly `done=true` and
`done_reason="stop"`; missing, boolean-like, unknown or length-limited completion
metadata cannot supply an executed action.
The message must be an assistant object. Native `tool_calls` must be absent or
an empty list; a competing native action cannot be ignored in favor of JSON text.

The controller serializes canonical UTF-8 once, sends those same application
body bytes, and stores their length and SHA-256. It stores bounded raw HTTP
response-body bytes as base64, their length/hash, HTTP status, a normalized
encoding label, outcome, reported usage and collector-observed timing. Headers,
endpoints and credentials are not persisted. Private grader fixtures and hidden
snapshot/check data are not added to agent requests.

The limits are 128 KiB per request, 64 KiB per recorded response, 200 events and
8 MiB of exact serialized events per episode. Before sending, the recorder
reserves space for both a start event and the largest bounded outcome event.
Oversized responses retain only the observed prefix. Nonidentity encoded
responses retain raw evidence but cannot supply an action. Cancellation,
transport failure and timeout finalize a paired outcome, including a received
prefix when available. Pairs become persistent when the handled episode is
finalized; they are not process-crash durable.

Recorded provenance includes the recording choice, full provider/recorder module
SHA-256 values, the exact contract/hash and reported daemon version. Its policy
hash includes the protocol, recording choice and evidence metadata. Replay
checks source compatibility, reconstructs the exact request from seeded state,
verifies byte integrity/outcome/usage, and links the parsed response action to
the executed action. This is consistency verification, not signed collection
authenticity or a provider/server execution attestation.

## Usage And Exports

Counts must be actual reported nonnegative integers at most `2**63 - 1`.
Missing, boolean, negative, oversized or malformed counts remain absent, not
zero. Reported model names must be nonempty, printable and at most 200 characters;
they are separate from configured model names and catalog digests. A reported
daemon version is limited to 80 printable characters. Aggregate `_known` values
and `_complete` flags distinguish partial known usage from complete totals.

Recorded JSON episodes are operator-only: `training_eligible=false`. SFT, DPO
and grouped-RL exports exclude them, including alternative candidate pools.
Raw trace exports and Harbor ATIF retain bounded evidence and failure outcomes.
ATIF actions/context remain normalized interchange, not a chronological model
transcript; original wire evidence is explicitly separate in `extra`.

Default JSON training eligibility and policy messages remain unchanged. Its
request and response safety checks are hardened too, but its failed-call bodies
are not recorded. Its aggregate usage covers executed decisions only; a failed
unrecorded attempt prevents a complete episode-total claim. Scripted providers
are unchanged.

All HTTP providers reject oversized or nonidentity raw bodies before parsing.
Local metadata reads are streamed and bounded to 64 KiB; discovery filters
cloud/invalid catalog entries. Nonloopback remote endpoints require HTTPS and
reject userinfo, query strings and fragments. Remote calls still require both
the server paid gate and per-run opt-in. Redirects and ambient proxies are off.
Public provider errors suppress underlying network/parser exception chains, so
direct SDK tracebacks do not print raw responses or connection details.

## Verification And Sources

```sh
uv run pytest -q tests/test_http_evidence.py tests/test_providers.py tests/test_atif.py
uv run ruff check src/world_engine/providers.py src/world_engine/rollout.py
PYTHONPATH=/tmp/world-engine-atif-upstream WORLD_ENGINE_ATIF_VALIDATE_UPSTREAM=1 \
  uv run pytest -q tests/test_http_evidence.py
```

The optional last command uses the pinned upstream installation described in
[ATIF documentation](atif.md). Tests use bounded mock HTTP streams; no live
model calls or comparative study are part of this source phase.

Primary references checked on 2026-10-10: Ollama's
[structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[model catalog](https://docs.ollama.com/api/tags),
[model details](https://docs.ollama.com/api-reference/show-model-details) and
[cloud behavior](https://docs.ollama.com/cloud). Upstream API source is pinned to
[`eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/api/types.go)
(MIT). This adapter does not vendor upstream code or add a runtime dependency.
