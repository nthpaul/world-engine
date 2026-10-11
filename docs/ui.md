# Local console

The React console reads the local World Engine API. It has no mock results or browser-stored run history. The API owns environments, providers, run execution, grading, and trajectory exports.

Start the API from the repository root:

```sh
uv run python -m world_engine serve --host 127.0.0.1 --port 8000
```

Start the console in another terminal:

```sh
cd web
npm ci
npm run dev
```

Open [the local console](http://127.0.0.1:5173). Vite proxies `/api` to `127.0.0.1:8000`. The console displays an offline state and retries when the runtime is unavailable. Run history refreshes every two seconds; the selected run refreshes every 1.5 seconds. Hash routes preserve links to individual runs.

## Workflow

Create a rollout with an environment, configured provider, model, episode count, seed, concurrency, step limit, and timeout. Scripted policies run without credentials. The local provider uses models available to the runtime. Remote providers remain disabled until the server enables its global paid-call gate; each remote run also requires an explicit checkbox. Credentials are configured on the server and never entered into the console.

Native Tools (`local-tools`, v1) and Native Ledger (`local-tools-ledger`, v2)
are separate local choices; Local Ollama (`local`) remains structured JSON.
Selecting either native choice checks and locks evaluation-only. Native runs
stay excluded from all training formats even when a task passes. Catalog
availability means an installed local model; preparation separately verifies
tool capability and digest. The API uses separately defined `NativeRunConfig`,
not a widened legacy config or changed shared grader module. These controls do
not themselves constitute a new native-model evaluation. Entering native mode
selects concurrency one; the operator can still explicitly choose one through
eight. Legacy modes retain default four. This is not a forced native cap or an
experimentally established optimal setting.

Inspect a run's episodes, termination reason, action arguments, tool results, observations, provider usage, action latency, and hidden grader checks. The provenance view shows the original run configuration, per-episode seed, scenario, split, final state hash, and frozen execution metadata. Recorded environment/grader versions, implementation hashes, model identity/digest, and stable lineage remain separate from the current registry version.

Exports download server-generated JSONL as raw traces, SFT, DPO pairs, or grouped RL trajectories. The quality selector restricts exports to passed episodes or includes all episodes. Empty DPO exports can be valid when a run has no usable preference pairs. Benchmark comparisons use observed completed episodes; matching seeds and bounds are necessary for meaningful policy comparisons.

The Harbor ATIF option downloads operator interchange as JSONL containing one ATIF-v1.8 document per episode. It preserves evaluation-only and held-out provenance instead of treating those documents as training exports; every ATIF document has `training_eligible: false`. See [the ATIF contract](atif.md) for upstream validation and the distinction between recorded controller context and provider transcripts.

## Verification

```sh
cd web
npm run build
npx playwright install chromium
npm run qa -- --output ../artifacts/qa/NEW_RUN
```

Use a new, unused output path for each run. The script refuses an existing directory, file or live/dangling symlink before opening a browser or making API requests. It does not prune prior videos, downloads or receipts. Paths are resolved relative to the `web` working directory in these commands.

`scripts/ui-qa.mjs` connects to the real API through Vite, launches scripted oracle/baseline rollouts, inspects traces and frozen provenance, exercises exports and input bounds, verifies navigation, and tests paid-call rejection. It records desktop and 390px mobile screenshots, a browser video, exported JSONL, and a machine-readable report under the selected output. Default QA makes no local or remote model calls. Its scripted runs remain in local API history.

The standard phase's optional `--local-cancel` explicitly authorizes a bounded installed-local-model cancellation probe. It is never enabled merely because a local provider exists. Run it only in a separately authorized inference window, never concurrently with a locked study. The ATIF and access phases reject that flag.

Set `WORLD_ENGINE_UI_URL` to run the same checks against another local preview address. Browser errors fail the check. Tables intentionally scroll horizontally at narrow widths; the document itself must not overflow.

Run the separate ATIF checks with `npm run qa -- --atif --output ../artifacts/atif/qa/NEW_RUN`. They create only a scripted evaluation-only batch, inspect failure-preserving ATIF downloads and passed-only filtering, and save screenshots, video, source fingerprints and a receipt. This phase makes no model calls and does not overwrite foundation QA artifacts.

Run access checks with `npm run qa -- --access --output ../artifacts/access-provisioning/qa/NEW_RUN`. This phase is scripted-only and checks the access workflow through the real API. At controller source `e1550290`, [v2](../artifacts/access-provisioning/20261010-ui-v2/ui-report.json) passed 31 checks: sixteen evaluation episodes, 121 decisions, thirteen desktop/360px/390px screenshots, ten byte-exact downloads and a 5.48-second VP9 recording. Reference passed eight tasks; baseline passed zero. Sampled label contrast was at least 4.756:1; no browser errors or document overflow were recorded. Tables retain intentional internal horizontal scrolling.

The [first attempt](../artifacts/access-provisioning/20261010-ui-v1/failure.json) failed when JavaScript numeric reserialization changed full operator replay bytes. Its raw evidence and failure receipt remain unchanged; v2 preserves operator JSON numerals during extraction. The [independent v2 validation](../artifacts/access-provisioning/20261010-ui-v2/independent-validation.json) checks all recorded source hashes, sixteen replays and actual pinned Harbor validations, all ten downloads, and sixteen exclusions per training format. UI controls are not access model-performance evidence; the [separate native study](access-native-results.md) failed all eight deadline-bounded attempts.

The separate [candidate corpus](../artifacts/candidate-corpus/20261010-v1/manifest.json) is a scripted CLI collection, not another browser run. Its 128 verified episodes and train-only exports do not change the v2 UI denominator or imply that a model was trained.

The [metric-only preflight](../artifacts/qa-metric-preflight/20261010-v2/report.json) reads the existing saved access baseline at 1440px, 390px and 360px. The throughput value stays numeric (`235.32`), with `steps/s / 68 ms elapsed` in its note; no body/metric-text overflow or browser errors occurred. Nineteen focused UI tests and a frontend build passed. This used the cached `e1550290` backend, created no episodes and made no model calls; it is not new full current-source acceptance.

## Later five-phase acceptance

At recorded source `b4501029a332d7675a12fbf84b00358230d3d154`,
[independent validation](../artifacts/qa/20261010-current-final-validation-v1/independent-validation.json)
reconciles five phases with **129 checks, 56 screenshots, five videos and 26
byte-exact downloads**. The standard/ATIF/access phases created 34 scripted
episodes. Two native inspection phases used unchanged imported v1/v2 receipts,
not new model executions. All 36 episodes replayed and validated against the
actual pinned Harbor model. Sixty training episode-format exclusions were
checked; standard candidate exports instead contained 52 SFT decisions, eight
DPO pairs and eight nontrainable groups. Older database candidates were
available, but all selected DPO pairs came from the fresh reference/baseline.

Final history was eleven runs/68 episodes, including prior history. The 98
original files totaled 21,210,254 bytes; the validation sidecar is additional
publication data. Root inspected every screenshot, decoded all videos, and
reviewed fifteen video frames. Source hash entries matched the recorded source;
later source changes require their own proof. The standard report lacks a
controller-source field, so its source is established by fresh episode
provenance, not an invented report attestation. Failed older UI receipts remain
preserved. Native CLI/default changes were separately committed at `ef63eda9`,
with focused mock/history checks and root's 1,547-test/six-optional-skip full
checkpoint, Ruff and frontend build. Later control-QA and actual API-receipt
inspection appear below; no native API model performance is inferred from
these earlier import inspection checks.

## Final native controls and actual-receipt inspection

At source `6bdec4f0281e51d502c505bda502ae5fe0c3dd2a`, corrected
[controls v2](../artifacts/native-controls-qa/20261010-v2/report.json) passed
fifteen checks with twelve screenshots, one video and 24 GETs. It never pressed
Start, made a POST, created an episode, imported history, downloaded data or
called a model. Explicit concurrency two remains editable. The original
[controls v1](../artifacts/native-controls-qa/20261010-v1/report.json) passed
automated checks but root visual review found a clipped 360px Start footer;
fourteen original files/1,782,398 bytes remain preserved as visual nonacceptance.
The corrected form scrolls while retaining a fully visible action footer.

Two later read-only phases inspect the actual source50 API smoke episodes:
[native v1](../artifacts/native-api-smoke/qa/20261010-v1/ui-report.json) and
[ledger v2](../artifacts/native-api-smoke/qa/20261010-v2/ui-report.json).
Each passed 25 checks with eleven screenshots and one video. Ten downloads
reproduce byte-for-byte: four operator/ATIF records totaling 336,303 bytes and
six empty unsupported-native training exports. Both episodes replay and
validate against actual Harbor; no new run, import, model call or POST occurred.
The strict API-wrapper mode is separate from the historical import-wrapper
contract. Incompatibility was identified offline; no old-mode preflight,
output reservation or browser was attempted. It was not a failed collection
or model attempt.

Together the three new phases passed 65 checks with 34 screenshots/three videos
and 54 original files/5,055,000 bytes. Root inspected all screenshots, decoded
all videos and viewed nine frames; the 360px footer is visible with no overlap.
Controller/startup source is51, while actual model episodes retain source50.
Database history stayed thirteen runs/70 episodes/no active jobs. Do not add
these checks to the earlier129 as an independent capability denominator or
retroactively replace failed receipts. All source51 CI gates and root's full
1,657-test/no-skip suite passed, including opt-in real Harbor/Docker checks.
