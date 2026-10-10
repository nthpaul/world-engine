# Native Ollama Tool Provider

This SDK-only adapter uses Ollama native `tools` through `OllamaToolsProvider`. The existing registered `local` provider still uses structured JSON actions. Native calls are operator-only: they are excluded from SFT, DPO and grouped-RL exports, including candidate pools, even when the episode passed on a training split. They are not a new console/API provider option.

## Protocol

`ollama-tools-v1` follows the primary [tool-calling guide](https://docs.ollama.com/capabilities/tool-calling) and [chat API](https://docs.ollama.com/api/chat). API types were inspected at Ollama revision [`eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/api/types.go), dated 2026-10-09. That upstream source is [MIT licensed](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/LICENSE); no upstream implementation or new runtime dependency is included.

Every decision sends a separate frozen native system message and one current observation/normalized action-result history user message, with exact observed tool definitions. These are the actual application inputs, not synthesized prior native assistant/tool turns. Hidden grader checks, private snapshots and expected fixtures are not sent. Settings are `stream=false`, `think=false`, temperature 0, 512 output tokens, and an 8192-token context setting. There is no retry, prompt repair, JSON fallback or inference-time model download.

Exactly one native tool call is accepted. Explicit `finish` is the only completion action. Text-only/no-call, multiple-call, malformed and length-truncated responses stop the episode as provider errors; no prefix is executed. No-call text is not automatically classified as a safety refusal. A structurally valid unknown tool is passed to the environment and counted as an invalid action. Original vendor IDs/index/content are retained in response evidence when present; absent vendor IDs are not invented. Recorder correlation IDs are collector-derived.

Preparation requires a loopback URL, an exact installed catalog entry with a 64-character digest, and tool capability from `/api/show`. Cloud names and reported `remote_host`/`remote_model` are rejected before inference. The catalog digest describes inspected metadata, not attestation that a particular weight file was used by a trusted server. A mutable tag or an untrusted daemon cannot be made authentic by recording its response. Reported model names are likewise not verified weights.

## SDK Use

```python
from world_engine import RunConfig
from world_engine.ollama_tools import OllamaToolsProvider
from world_engine.rollout import rollout

config = RunConfig(environment_id="refund-ops", provider_id="local", model="qwen3:8b",
                   evaluation_only=True, concurrency=1, max_steps=20, timeout_seconds=120)
provider = OllamaToolsProvider(config)
try:
    await provider.prepare()
    episode = await rollout(config, 0, provider)
finally:
    await provider.close()
```

`RunManager.submit(config, provider=provider)` also supports this custom provider and manages preparation/closing. Direct `decide` calls without an active rollout recorder are rejected. Episode-local `ContextVar` buffers prevent one shared batch provider from mixing concurrent episode evidence. No conversation state is stored on the provider.

## Evidence And Boundaries

Finalized episodes contain paired `provider_events` with exact UTF-8 serialized request bytes actually sent as HTTP content (128 KiB maximum) and raw HTTP entity-body response bytes encoded as base64 (64 KiB maximum). Native reading uses `aiter_raw`, not automatic decompression. Only identity encoding is accepted; a server that ignores `Accept-Encoding: identity` produces an explicit encoding failure with bounded raw evidence, never a parsed action. Byte SHA256, decision index, collector correlation ID, observed times, duration, HTTP status, a bounded encoding classification, safe outcome and reported usage are recorded. Endpoints, other headers and credentials are not persisted. Invalid raw text remains only in operator evidence, not the safe error string. Preparation metadata uses bounded decoded JSON, not raw-response evidence.

An episode has an 8 MiB serialized event budget, including array framing. Before starting a request, the recorder reserves its exact start-event size plus maximum base64 response size and 4096 bytes for bounded outcome metadata. If the reservation cannot fit, no request or unpaired start is emitted. Reported numeric usage must fit a nonnegative signed 64-bit integer and normalized model metadata is limited to 200 printable characters; other values remain unknown/omitted in normalized usage and visible only in raw evidence. A near-cap regression exercises large malicious reported model names/counts while retaining all paired raw outcomes and refusing the next request.

`body_complete` means the whole HTTP body was read. `complete` means a full accepted native protocol reply; invalid or truncated replies are false. Oversized/incomplete responses keep a bounded observed prefix and declare `response_hash_scope=observed-prefix`; its hash is not a hash of the unavailable full response. Timeout/cancellation emits the paired outcome in `finally`. Request-attempt counts are not proof of actual model execution. Missing token counts remain absent, with completeness flags and separately summed known counts, never fabricated zero. A reported zero is preserved.

The recorder stores events only when an episode is finalized or handles an abort. It is explicitly not a crash-durable request journal. Source module/recorder hashes, frozen prompt/options contract hash, daemon version, configured model and inspected catalog digest accompany evidence. Replay checks byte integrity, protocol/source fingerprints, exact request reconstruction from seeded observations/history/tools, and successful action linkage. Replay verifies consistency, not signed collection authenticity, server-rendered tokens, reproducibility or failed network causes.

Raw operator traces preserve events and evaluation flags without grader checks/private snapshots. ATIF remains normalized operator interchange with native evidence in `extra`, not a chronological native-provider transcript or Harbor trial result. All native training exports remain disabled until a separately reviewed trainer format defines the real tool protocol, targets and loss boundaries.

## Locked Experiment

The example collector performs no inference without explicit `--collect`, an authorized committed source revision and a clean implementation/collector/relevant-test scope. It rejects existing output directories and model digest changes. The protocol fixes three worlds (`crm-merge`, `refund-ops`, `incident-control`), two seeds (42 and 730), six episodes maximum, 20 steps/120 seconds per episode, concurrency 1, and a 15-minute overall bound. Every finalized failure is saved before proceeding. No prompt tuning or retry is performed.

All collector artifacts, including its isolated SQLite database and three JSONL representations, have a 64 MiB total cap. Before another episode, a conservative reservation covers bounded episode copies/database overhead and a 256 KiB report reserve. An individual full episode JSONL record is limited to 12 MiB; unexpected larger records are retained raw within the reservation, mark collection failed, and omit duplicate formats. Bounded writers independently check actual artifact bytes before writing. A cap failure is explicit in the report and prevents subsequent inference; it never silently drops a response while claiming successful collection. Reports record all imported source-module hashes plus the collector and relevant test hashes. The cap can stop the experiment early; it does not promise all six episodes regardless of size.

```sh
uv run python examples/native_tool_benchmark.py --collect \
  --source-revision REVIEWED_COMMIT_SHA \
  --output artifacts/native-provider/UNIQUE_EXPERIMENT_DIRECTORY
uv run pytest -q tests/test_native_provider.py
```

The predeclared installed `qwen3:8b` digest is `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`. Source and protocol must be committed and collection explicitly authorized before running the first command. The six cases are a small synthetic evaluation, not a leaderboard score, population estimate, trainer-ready dataset or comparison against prior JSON-mode receipts. Terminal-Bench remains a separate public evaluation and is never imported here.
