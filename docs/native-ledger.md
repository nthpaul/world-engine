# Native event ledger candidate

`world_engine.native_ledger` implements a pure candidate request builder named
`ollama-tools-ledger-v2`. It is not wired into the provider, rollout, CLI, API,
or replay dispatcher. The existing `ollama-tools-v1` protocol and its recorded
requests remain unchanged. This document does not authorize inference or a
comparison collection.

## Public interfaces

```python
from world_engine.native_ledger import request_body, request_from_context, reconstruct

# The controller supplies the public observation returned by reset.
body = request_body(model, initial_observation, current_observation, history)

# Existing controller histories capture policy_input before each action.
same_body = request_from_context(model, current_observation, history)

# A single inverse reconstructs only the recorded public data.
public_context = reconstruct(body)
assert public_context["initial_observation"] == initial_observation
assert public_context["observation"] == current_observation
```

The module performs no transport, filesystem, grading, snapshot, provider-state,
or model operations. Inputs must be detached public observations and controller
history. `reconstruct` returns detached dictionaries.

`request_from_context` uses the current observation when history is empty.
Otherwise it extracts the initial public observation from the first step's
generic controller `policy_input`. That input must be the exact result of
`providers.policy_messages(initial_observation, [])`. It is not the native wire
request, an authentication record, or grading truth.

The explicit builder does not require `policy_input`. When a step includes it,
the builder checks it against that step's reconstructed pre-action observation
and preceding action/result history. No private trace fields enter the request.

## Wire layout

The request retains the existing native system prompt, native function tools,
model options, `stream=false`, `think=false`, and `keep_alive="5m"`.
It does not introduce JSON-format fallback or assistant/tool dialogue.
The user content contains canonical JSON lines:

```text
{"initial_observation":{...static metadata and initial dynamic fields...}}
{"action":{...},"decision_index":0,"observation":{...dynamic fields...},"result":{...}}
{"action":{...},"decision_index":1,"observation":{...dynamic fields...},"result":{...}}
```

Static public fields are `environment_id`, `version`, `task`, and `tools`.
`tools` appears only in the request's native function definitions. The first
line contains the remaining static fields plus the initial `role`, `state`,
`done`, and optional `tick`. Each later frame records the action, result, and
full post-action dynamic observation. Reconstruction restores the static fields
and the native tools into every observation without losing their original names,
descriptions, or argument schemas.

For the same model and initial observation, extending coherent history appends
one newline and one frame to the user content. All existing content stays an
exact character prefix; system, tools, and options stay equal. This is not an
exact prefix of the entire serialized HTTP body: the closing user-content quote
and the following JSON fields necessarily move. JSON escaping keeps embedded
newlines in task or state values inside their frames.

The closed observation envelope supports the four current reference worlds.
An unknown top-level observation field is rejected rather than guessed public.
A new public envelope requires an explicit protocol change. Nested `state`
content is supplied by the trusted observation boundary; this builder cannot
classify a caller's arbitrary nested value as public or private.

## Validation and limits

Validation uses canonical, type-sensitive comparisons. `true`, `1`, and `1.0`
are not interchangeable. The builder rejects changes to static metadata,
nonconsecutive indices, missing or altered observation fields, controller
context mismatches, and a current observation that differs from the final
history observation. Where observations expose ticks, reset must start at zero
and every attempted action advances one tick. Rejected actions must preserve
public state and role. A request after a terminal observation is rejected.

These checks establish internal coherence, not world execution or collection
authenticity. A caller can invent a coherent successful action and state change.
Only trusted replay against the reset world can reject that invention. The
builder never invokes a world, evaluator, reference policy, or snapshot loader.

Limits remain compatible with the native recorder:

- The full canonical request must fit `MAX_REQUEST_BYTES`, currently 128 KiB.
- Response and episode evidence limits are copied into the candidate contract;
  this pure builder does not receive or enforce transport responses.
- At most 99 historical decisions leave room for the current request under the
  existing 200-event limit. No post-finish request is representable.
- JSON depth is at most 64, a validated value has at most 32,768 nodes, and
  integer magnitude is at most 4,096 bits. Nonfinite floats, non-JSON Python
  values, invalid UTF-8 strings, cycles, and oversized text fail closed.
- Validation errors contain generic reasons, not supplied values or chained
  parser exceptions.

The normalized builder retains every public post-action observation. This can
use more bytes than v1 when public state is large or changes often. It also
fails once the complete request crosses the unchanged cap; it does not truncate
history or silently remove public state.

## Possible integration, not implemented

The smallest later integration would reuse `OllamaToolsProvider`'s existing
preflight, one-call parser, recorder, limits, cancellation, and cleanup. It would
add an explicitly selected request-context protocol, not a copied provider or
a second transport implementation. `decide` could call `request_from_context`
for v2, leaving v1's request builder intact. No conversation cache or mutable
initial-state field is needed.

Replay would dispatch on the explicit provenance protocol. For v2 it would
first reconstruct the stored request, then independently reset the pinned world
and compare the initial observation, every executed action/result/post-action
observation, and the current observation. Replay must regenerate the same v2
request and require exact canonical wire bytes and the existing request/response
event linkage. A protocol mismatch must reject, never fall back to v1.

Before integration, provenance must record the v2 contract and the ledger module
fingerprint alongside the existing provider and recorder fingerprints. Editing
the shared provider or replay source changes source-pinned replay requirements
even if v1 semantics stay unchanged. Existing receipts require their recoverable
collection revision; none should be rewritten to look like v2. Raw native
records remain operator interchange with `training_eligible=false` unless a
separate training contract is established.

A later locked comparison should use declared source revisions, identical
scenario budgets and model identity, and fresh immutable output. It should
retain failures and cancelled attempts, not compare successful calls alone.
Wire-byte counts are not tokenizer counts. Append-stable content does not prove
Ollama prefix-cache reuse, cache hits, latency reduction, or higher throughput.

## Why this candidate

The ledger has one normalized representation and one inverse. It needs no
provider state and can reconstruct intermediate public observations that v1's
action/result-only history omits. Static tool schemas appear once.

A faithful assistant/tool dialogue is another viable protocol. It would retain
actual assistant messages and tool-call IDs, with linked tool responses and
public observations. That design needs accepted raw response events as an
additional input and explicit rules for missing IDs, rejected or cancelled
calls, and daemon-specific message shapes. It is a larger compatibility change.
The normalized ledger deliberately does not claim to preserve those assistant
messages; the existing raw recorder still owns them.

## Local verification

```sh
uv run pytest -q tests/test_native_ledger.py
uv run ruff check src/world_engine/native_ledger.py tests/test_native_ledger.py
```

The tests use pure fixtures and the local scripted policy against all four
reference worlds. They exercise exact prefixes, reconstruction, rejected
actions, detached outputs, metadata and context mutations, type substitutions,
terminal requests, malformed wire records, and bounded JSON failures. They make
no model or network calls.
