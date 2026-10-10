# Bring Your Provider

Start with the credential-free SDK example:

```sh
uv run python examples/custom_provider.py
uv run pytest -q tests/test_custom_provider_example.py
```

It performs two deterministic actions, `inspect` and `finish`, using public
observation/history only. It does not solve the business task or call a model.
The resulting evaluation-only episode records the actual custom class/source
hash, configured mock model, `provider_id=custom`, termination, and replay result.
The example writes no files and reads no credentials.

## Built-In Adapters

| Selection | Exact supported interface | Configuration |
|---|---|---|
| `local` | Ollama `POST /api/chat`, nonstreaming structured JSON action | `WORLD_ENGINE_LOCAL_URL`, default `http://127.0.0.1:11434`; exact installed `model` tag |
| SDK `OllamaToolsProvider` | Ollama native tools, exactly one tool call per decision | Same local URL; installed model must advertise tools capability; not a console provider option |
| `openai` | Chat Completions-compatible `POST /chat/completions`, JSON text action | `OPENAI_API_KEY`; `WORLD_ENGINE_OPENAI_URL`, default `https://api.openai.com/v1`; configurable `model` |
| `anthropic` | Messages-compatible `POST /messages`, JSON text action | `ANTHROPIC_API_KEY`; `WORLD_ENGINE_ANTHROPIC_URL`, default `https://api.anthropic.com/v1`; configurable `model` |

These are narrow adapters, not universal vendor compatibility. The OpenAI path
uses `temperature=0`, `max_tokens=512`, and `response_format=json_object`; it does
not implement Responses API or native hosted tool calling. Anthropic uses a
system prompt, `max_tokens=512`, `temperature=0`, `x-api-key`, and API version
`2023-06-01`; extended thinking, cloud-platform IAM, workspace headers and other
vendor options are not exposed. A model requiring different parameters needs a
reviewed custom SDK provider. UI discovery is not an exhaustive remote model list;
CLI `--model` and SDK `RunConfig.model` accept an explicit name.

Local JSON requires completion capability, an exact installed catalog tag/digest,
and a final assistant response with `done=true`, `done_reason=stop`, no nonempty
native tool calls, and valid `{"tool": "...", "args": {}}` text. Both local modes
reject cloud models, remote catalog markers and nonloopback endpoints; neither
pulls models. JSON uses `think=false`, temperature 0, 512 predicted tokens and
8192 context tokens. Reasoning/model capability varies; malformed or truncated
actions fail rather than triggering a retry or fallback.

## Keys And Consent

Supply keys in the environment of the server or CLI process through your secret
manager or a silent shell prompt. Do not put secrets in run JSON, labels,
observations, repository files, screenshots, URL userinfo/query parameters, or
custom provider error strings. The console has no key-entry field.

Remote execution requires **both** `WORLD_ENGINE_ALLOW_PAID=1` in that process and
`allow_paid=true` for that run (CLI `--allow-paid`). Neither alone enables a call.
Keys loaded after server startup require restarting with the intended environment.
The API health/console runtime view shows readiness and the global paid gate,
not secret values. Nonloopback remote endpoints require HTTPS; redirects and
ambient proxy configuration are disabled. URL overrides are API base URLs,
including `/v1` when required, not full `/chat/completions` or `/messages` paths.

The following is a **paid-call template, not a command executed by this guide**.
First inject `OPENAI_API_KEY` securely and choose a compatible model you can use:

```sh
WORLD_ENGINE_ALLOW_PAID=1 uv run python -m world_engine \
  --db .world-engine/my-provider-check.sqlite3 rollout \
  --environment crm-merge --provider openai --model YOUR_COMPATIBLE_CHAT_MODEL \
  --allow-paid --episodes 1 --concurrency 1 --max-steps 2 --timeout 30 --evaluation-only
```

For Anthropic, use `ANTHROPIC_API_KEY`, `--provider anthropic`, and a compatible
Messages model. A compatible alternative endpoint still uses the corresponding
key variable and double gate. Bounds limit episodes, decisions, response tokens,
concurrency and cooperative elapsed time; **there is no dollar spending cap**.
Cancellation cannot retract work already accepted by a remote service. Start with
mock coverage and one explicit evaluation-only episode before broadening a run.
No hosted calls were made to validate this guide; adapter tests use mocked HTTP.

## Custom SDK Contract

Implement `async decide(observation, history) -> Decision`. Return a parsed
`Action(tool=..., args=...)`, and actual reported usage only. Real model adapters
using per-decision counts must set `tracks_reported_usage = True`: the runner then
keeps missing counts unknown and marks aggregate completeness explicitly. Generic
custom providers without this flag inherit legacy sum-to-zero totals; those totals
must not be interpreted as observed model usage. Do not invent absent counts.
The environment validates tool names/arguments and
records invalid actions. Use `ProviderError` with a safe redacted message for a
known failure. Never attach credentials or raw response payloads to public errors.

For direct `rollout(config, index, provider)`, the caller prepares and closes the
provider in `try/finally`, as the mock example does. For
`RunManager.submit(config, provider=provider)`, the scheduler owns preparation and
closing for the batch. A batch may call `decide` concurrently: keep mutable
conversation/request state episode-local, derived from the supplied history.
Per-run `max_steps`/timeout/concurrency still apply, but arbitrary Python providers
are trusted extensions, not a sandbox or automatic paid-call gate. A custom
adapter must enforce its own endpoint, credential, response-size and cost policy.
See [cleanup semantics](provider-lifecycle.md).

Recorded `policy_input` is the controller context, not proof of what a custom
provider sent. Class/source hashes are useful provenance, not recursive dependency
attestation or verified model weights. Keep experimental adapters evaluation-only.
Do not assume a custom response protocol is trainer-ready. Local native and
recorded-JSON modes are explicitly excluded from training exports; their bounded
wire evidence and limitations are documented in [native provider](native-provider.md)
and [recorded JSON provider](json-provider.md). Replay proves trusted transition,
grading and envelope consistency, not authentic remote execution.

Primary interface references: [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[Ollama tools](https://docs.ollama.com/capabilities/tool-calling),
[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
and [Anthropic API overview](https://platform.claude.com/docs/en/api/overview).
Adapter behavior above is the repository implementation, not a claim that every
current vendor model or authentication option is supported.
