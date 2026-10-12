# Fixed browser loop diagnostic and stronger-model qualification

This protocol declares two separate local experiments. It does not change the
archived V7 attempt or its grade. The diagnostic asks whether a request returns
the same current-node click in one retained looping context. The real cohort
tests an actual browser workflow using the corrected v3 interface. Neither
experiment is training data or evidence of general model capability.

Source, collectors, tests and this protocol must be reviewed, committed and
pinned before collection. The default commands print plans and contact nothing.
An operator separately authorizes execution and restarts the browser API at the
reviewed revision for the real cohort. No downloads, paid calls or fallback
models are permitted.

## Fixed inputs and local models

The diagnostic reads a privately supplied regular file. It must be the retained
749,066-byte V7 model-attempt copy with SHA256
`de94a2b141116de7e994402a7ca503fea6d419e51bbba047bd4bccea6a218336`.
The attempt ID is `642ee1fd-0079-4b55-92d7-4978a8142a1a`.
Decision fourteen, zero-based step thirteen, has thirteen completed actions and
seventeen remaining actions. Its archived request is 10,836 bytes with SHA256
`bae172d3c9ea22bb241066c5f13ec171aeaa6f5a69d785184ed10e04390c4c3b`.
Journal integrity and request/context correspondence are checked before any
client is created. Unkeyed hashes detect edits relative to these retained pins;
they do not independently authenticate the recorder or the application.

Only the recorded public instruction, current AX observation and completed
action/result/post-observation history are projected. Grades, expected fixtures,
sealed state, credentials and operator snapshots are not forwarded. The full
input stays private. The projected public context and exact request bytes are
written in the fresh diagnostic output before each chat request.

The allowlist fixes existing local public models:

| Model | Required model digest |
|---|---|
| `qwen3:8b` | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| `qwen3:32b` | `030ee887880fc378860c2dd35101da424377520441ae4bfe7be6deff8ade7840` |

Preparation requires a local native-tools-capable model, captures the exact
installed `/api/show` template UTF-8 hash and daemon version, and checks the model
digest before and after chat. A template change between cells using the same
model stops the diagnostic. Whole catalogs, raw templates, other model names and
headers are not saved. Metadata checks are not model generation requests.

All cells and the real model slot use temperature zero, `think=false`, 512 output
tokens, context 16,384, nonstreaming native tools and `keep_alive=5m`. These options
are fixed, not proof of deterministic inference. The new v3 request retains
normalized accepted tool actions, linked public transitions, absolute completed
steps, remaining budget and unchanged-observation feedback. It does not invent
raw historical call IDs or recover omitted model reasoning.

## Diagnostic matrix

The fixed sequential order is archived 8B, corrected 8B, archived 32B, corrected 32B.
Each cell sends at most one `/api/chat` request, with no retry. The archived8B body
is byte-identical to the retained V7 request. Archived32B changes only its `model`
field and is explicitly not byte-identical to the archive. Corrected bodies are
constructed by the current `OllamaBrowserPolicy.request_body` without resetting
an application or consulting a grader. No returned action is executed.

The primary descriptive classification is `repeated_click` for a valid current
`Click` on node385, `other_valid_action` for another schema-valid permitted action,
or `invalid_response`. Node actions require one current observed ID. Navigation
must pass the driver's same-origin document boundary. A different action, wait or
finish does not prove navigation progress, committed effects or task success.
Four single samples cannot isolate context/model causality or estimate a success
rate. Fixed order, model load state, shared hardware and swap remain confounders.

Each cell has a cooperative 180-second deadline and a separate three-second
client-close bound. The aggregate deadline is 780 seconds with 30 seconds reserved
for finalization. Requests are bounded by 128 KiB, responses by 64 KiB and the whole
diagnostic by 16 MiB including a reserved 1 MiB report. A complete raw reply is saved
before parsing. Transport failures retain their exact bounded prefix, marked
incomplete; timeout, transport/identity/source failure or uncertain client closure
stops later cells. Closing an HTTP client does not prove daemon generation has
stopped. Missing usage counts stay absent; known token counts and nanosecond
duration are descriptive, with explicit token-count completeness.

```sh
uv run python scripts/diagnose_browser_policy.py
uv run python scripts/diagnose_browser_policy.py --collect \
  --input /private/operator-supplied/attempt.json \
  --source-revision REVIEWED_FULL_SHA --output /private/fresh/loop-diagnostic
```

The input path is an operator placeholder, not a repository fixture. Existing
outputs, including dangling symlinks, are refused before source/input/network
work. No cells are re-run in an existing directory. Failures and unattempted
cells remain recorded.

## Real cohort, schema v8

`scripts/collect_gitlab_triage.py` now declares
`world-engine.triage-qualification.v8` and requires `ollama-browser-tools-v3`.
Historical schema v7 receipts and their pinned collector remain historical;
they are not recollected or silently relabeled. The reference protocol remains
`public-ax-triage-control-v7`. The four control slots retain their order, tasks,
seeds and budgets: incomplete 42, changes-required 42, already-correct 43 and
close-compatibility 42. Every control must satisfy the existing outcome, terminal,
cleanup and no-reconciliation gate before the optional model slot is admitted.

The separately authorized stronger-model invocation uses only `qwen3:32b` at
seed 42, 30 steps and 600 seconds. The API policy still has its existing 90-second
per-reply HTTP timeout; this experiment does not silently lengthen it. Default
`--model qwen3:8b` remains available, but is not an additional authorized model
attempt. There is one optional model slot, no automatic retry or fallback.

The real collector retains the existing 6,000-second aggregate deadline and
640 MiB total evidence cap, exact raw API responses and registered artifacts,
source/API-startup gates and cleanup requirements. It records actual policy
digest, protocol, options and template hash. Submission or completion uncertainty
requires operator reconciliation, not a hidden replacement attempt.

```sh
uv run python scripts/collect_gitlab_triage.py --model qwen3:32b
uv run python scripts/collect_gitlab_triage.py --collect --include-model \
  --model qwen3:32b --source-revision REVIEWED_FULL_SHA \
  --api-startup-revision REVIEWED_FULL_SHA --output /private/fresh/triage-v8
```

Report the actual task outcome separately from provider/transport failure, budget
truncation, invalid actions and cleanup. Reference footage must not be presented
as model footage. Source manifests and API startup attestation are distinct.
Retained private context comes from the project's synthetic GitLab fixture;
this protocol grants no new rights to external datasets or protected benchmarks.

## Metadata-bound repair and fresh diagnostic v2

The first actual diagnostic collection is retained unchanged as diagnostic-v1.
Both 8B cells returned the repeated current-node click 385. Preparation of the
first 32B cell then stopped because its installed `/api/show` response was
75,727 bytes, above the shared 64 KiB response bound. No 32B chat request was
sent, and the corrected 32B cell remained unattempted. This is a metadata-bound
failure, not evidence about the 32B model's browser decision or task ability.

The reviewed repair permits at most 256 KiB only for `/api/show` metadata.
The 64 KiB response bound above still applies to chat, `/api/tags` and
`/api/version`; the 128 KiB request bound is unchanged. Metadata is read as
bounded raw identity-encoded bytes before JSON parsing. Only the selected public
template hash is retained, not the full template or other installed models.
The real collector's separate 64 KiB preflight reads `/api/tags`, not `/api/show`;
its subsequent browser-policy preparation uses the repaired show-only bound.

A separately reviewed source pin owns a fresh diagnostic-v2 directory and the
future schema-v8 real cohort. Diagnostic-v2 runs the same four-cell matrix from
the beginning; it does not resume or overwrite diagnostic-v1. Repeated 8B cells
are declared new samples in a separate collection, not hidden retries or an
independent population. Options, order, archived context, deadlines, model
digests, tasks, reference controller, fixtures and grader are unchanged.
The real cohort has not started at this repair checkpoint. Root must review
and commit the repair before any new inference, then separately authorize
collection and restart the API at the same reviewed pin before the real cohort.

## Transport follow-up and fresh real cohort v9

The schema-v8 cohort at `241fd2362341387b307a7cd7ef2e8504ba94767c`
completed all five slots. The four controls qualified. The actual dense
`qwen3:32b` attempt `4c8ce22b-eafc-4e13-8628-4edbf5e26b88` accepted three
clicks, then failed with `provider_error` on its fourth inference request.
The recorded failure has no response status or body bytes. Its isolated grade
is zero; cleanup completed without reconciliation. The old recorder did not
retain the transport exception category, so that prefix alone cannot establish
the precise timeout type or prove that daemon computation stopped.

The follow-up makes transport settings explicit. The browser policy receives
the declared episode timeout, validates the existing 30--600-second range and
uses HTTPX connect/write/pool limits of ten seconds and a read limit of
`min(episode_timeout, 180)` seconds. These are phase inactivity limits, not an
end-to-end request deadline. The runner's existing outer episode timeout is
still authoritative and can cancel a request sooner. The recorded preparation
and transport-failure evidence include effective limits; failures retain a
fixed redacted category and elapsed time alongside their original raw prefix.
Client closure still does not certify daemon closure.

The v3 request body, native tools, generation options, task, fixtures, grader,
reference controller and permissions remain unchanged. This transport change
does not turn the failed v8 attempt into a successful or resumed attempt.

The separately reviewed schema-v9 collector adds one already cached local
candidate, `qwen3:30b-a3b`, with exact required digest
`0b28110b7a3364296d5cef609095537189fbb81547761de69fd22dd68d2166c2`.
Its mixture-of-experts architecture motivates a lower-latency candidate; no
browser-success or throughput advantage is assumed. Local identity and native
tools/template checks remain mandatory. There are no new downloads or paid
resources.

After source review, commit, green CI and a fresh API startup at that pin, the
operator may authorize exactly one fresh full cohort: the same four controls,
then one `qwen3:30b-a3b` triage attempt with seed 42, 30 steps and 600 seconds.
The effective read limit for that model slot is 180 seconds. All control gates,
aggregate 6,000-second/640-MiB limits, raw-evidence requirements and cleanup
conditions remain unchanged. No new diagnostic matrix, automatic retry,
fallback, task hints or in-place tuning is included. Preserve v8 and all prior
failures. Report the follow-up as a new declared sample with changed transport
and model factors, not an isolated causal comparison or a success-rate estimate.

```sh
uv run python scripts/collect_gitlab_triage.py --collect --include-model \
  --model qwen3:30b-a3b --source-revision REVIEWED_FULL_SHA \
  --api-startup-revision REVIEWED_FULL_SHA --output /private/fresh/triage-v9
```
