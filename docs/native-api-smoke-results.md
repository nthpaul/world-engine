# Native API integration smoke results

On 2026-10-10, the root controller collected the two fixed attempts declared in
[the native API smoke protocol](native-api-smoke-protocol.md). Both native API
aliases completed the same refund task and passed trusted evaluation. This is
integration evidence for two bounded executions, not a capability score or a
v1/v2 performance comparison. No CLI inference or console-initiated inference
was collected in this check.

## Workload and outcomes

Collection source was `8b82c7aa5ac944ec35b62ef2d12f28f4b8d254cb`, source 50.
Each alias received one `refund-ops` version `1.1.2` episode at seed `54000`,
with twenty decisions, 35 seconds, concurrency one, evaluation-only true, and
paid consent false. The installed public model was `qwen3:8b`, catalog digest
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
Native options stayed at temperature zero, thinking disabled, 512 predicted
tokens, and an 8192-token context setting. There were no retries or fallbacks.

| API provider | Terminal outcome | Decisions / invalid | Recorded native requests | Reported input / output tokens | Episode seconds |
|---|---|---|---|---|---|
| `local-tools` | Completed, finished, passed, reward 1.0 | 5 / 0 | 5 accepted | 6,387 / 152, complete | 8.936292374972254 |
| `local-tools-ledger` | Completed, finished, passed, reward 1.0 | 4 / 0 | 4 accepted | 5,146 / 137, complete | 4.022780750063248 |

The v1 attempt inspected the state, then requested approval, issued the exact
8,900-cent refund, closed the ticket, and finished. V2 requested approval,
issued the refund, closed the ticket, and finished without the extra inspection.
Both preserved the pre-existing payment and unrelated operational state.
Different decision counts and fixed execution order make these durations
unsuitable for a speed claim. Token counts are daemon reports, not independent
tokenizer measurements or proof of untruncated context consumption.

The collector completed in `15.01348758302629` seconds through cleanup and source
postcheck, before the final report write. It captured 59 API responses:
two admissions, two health reads, 53 bounded summary polls, and two owned run
details. Two client model-tag metadata attempts are counted separately; raw
catalogs were deliberately not saved. Server preparation metadata requests were
not observed. All nine recorded native chat requests were accepted, with no
cancellation or missing usage. Their reported totals were 11,533 input and
289 output tokens. There were no stopped, inconclusive, or unattempted slots.

## Original evidence and independent proof

The original [collector report](../artifacts/native-api-smoke/20261010-v1/report.json)
and 61 other files total 822,301 bytes. Its 19,630-byte report has SHA256
`68f61629ec92f851616d97b59346e715e8468acc04c79bd651e46cbcc877a359`.
The [validation sidecar](../artifacts/native-api-smoke/20261010-v1/independent-validation.json)
is a later publication addition, excluded from that original total.

The engine worker independently checked every original file hash, all 59
raw-body journal references, and the two ordered owned admission identities.
Every captured API body was complete and identity-encoded. The 22 source-file
hashes matched the source-50 committed blobs and current unchanged implementation.
The captured scope was clean; overall checkout dirtiness was recorded separately.

Each full episode is an original single-line, float-preserving wrapper:

- [Native v1](../artifacts/native-api-smoke/20261010-v1/local-tools-episode.jsonl), run `8737ad2f-1c35-4417-8932-c6b25c708d47`.
- [Native ledger v2](../artifacts/native-api-smoke/20261010-v1/local-tools-ledger-episode.jsonl), run `3a2eccd7-7f97-4d6f-92e4-c8e124fe7c7c`.

Both wrappers matched the terminal API details, fixed configs, and read-only
SQLite episode text/content hashes exactly. Seeded replay verified transitions,
authoritative grades, source/model/protocol identities, and all nine request and
response byte hashes. Both ATIF conversions validated against Harbor's actual
pinned `Trajectory` model, revision
`09f5b964f8e5075f7e52fd08c9994dfc80ad5d24`, schema SHA256
`892a423ee9c710e8067740b36dd15c9de2f0157d05b6c1ea30acc25ff1c4da6c`.

Six real SFT/DPO/grouped-export checks in an isolated temporary Store returned
no records and one `unsupported_provider_protocol` exclusion per check. Passing
native episodes remain operator-only, not training candidates. Protected original
wrappers can contain snapshots and grader diagnostics; exported trace and ATIF
downloads exclude those private fields. Validation made no model calls, API
requests, or primary database writes. Root separately confirmed these checks.

The source-50 server startup was root-attested at `2026-10-10 11:24:58 UTC`,
PID `33196`, with `WORLD_ENGINE_ALLOW_PAID=0`. Startup revision is an operator
attestation, not cryptographic authentication by the health package version.
Catalog digests and recorded transport do not attest daemon weight execution.
Read-only database integrity was `ok`, with thirteen runs, seventy episodes,
and zero active jobs after collection, up from eleven runs and 68 episodes.

Replay originals without inference or database access:

```sh
uv run python -m world_engine replay --file artifacts/native-api-smoke/20261010-v1/local-tools-episode.jsonl
uv run python -m world_engine replay --file artifacts/native-api-smoke/20261010-v1/local-tools-ledger-episode.jsonl
```

## Later read-only console proof

The console worker then inspected both original runs without importing them,
starting runs, or making model calls. Controller source was
`6bdec4f0281e51d502c505bda502ae5fe0c3dd2a`, source 51; the episodes retained
their source-50 provenance. Root restarted the same database at source 51 at
`2026-10-10 11:37:44 UTC`, PID `74741`, with paid calls disabled.

| Read-only phase | Checks | Screenshots / videos | Original files / bytes |
|---|---|---|---|
| [Native v1](../artifacts/native-api-smoke/qa/20261010-v1/ui-report.json) | 25 | 11 / 1 | 20 / 1,662,418 |
| [Native ledger v2](../artifacts/native-api-smoke/qa/20261010-v2/ui-report.json) | 25 | 11 / 1 | 20 / 1,607,843 |

Both phases preserved the original wrapper bytes, full canonical episode numeric
types, labels, configs, provenance, and complete usage. All ten downloads were
byte-exact output from the real exporter: two traces, two ATIF documents, and
six empty training files, totaling four rows and 336,303 bytes. Independent
checks validated both downloaded ATIF documents against the actual pinned Harbor
model and confirmed all six structural training exclusions. Each UI source
manifest had 28 files, all matching committed source-51 blobs and current bytes.

API originals and these two UI phases comprise 102 unchanged files and
4,092,562 bytes. The sidecar records their separate inventories. Root inspected
the screenshots and fully decoded both 1440x960 VP9 videos, each 2.44 seconds,
with no clipping or incoherent overlap. Mobile gray letterboxing and internal
table/JSON scrolling were intentional.

The separate [corrected native-controls phase](../artifacts/native-controls-qa/20261010-v2/report.json)
belongs to the console controls publication, not the API/UI total above. Its
15 checks and twelve screenshots cover default one-worker native selection,
explicit two-worker retention, evaluation-only locking, and visible action
buttons. The prior controls phase is retained with its root-observed 360px
footer-clipping defect, which the original automated checks missed. Source 51
fixed dialog scrolling and added button-geometry checks before recollection.
