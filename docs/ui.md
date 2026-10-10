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

Inspect a run's episodes, termination reason, action arguments, tool results, observations, provider usage, action latency, and hidden grader checks. The provenance view shows the original run configuration, per-episode seed, scenario, split, final state hash, and frozen execution metadata. Recorded environment/grader versions, implementation hashes, model identity/digest, and stable lineage remain separate from the current registry version.

Exports download server-generated JSONL as raw traces, SFT, DPO pairs, or grouped RL trajectories. The quality selector restricts exports to passed episodes or includes all episodes. Empty DPO exports can be valid when a run has no usable preference pairs. Benchmark comparisons use observed completed episodes; matching seeds and bounds are necessary for meaningful policy comparisons.

## Verification

```sh
cd web
npm run build
npx playwright install chromium
npm run qa
```

`scripts/ui-qa.mjs` connects to the real API through Vite, launches matched oracle/baseline rollouts, inspects traces and frozen provenance, exercises nonempty exports and input bounds, verifies navigation, tests the paid-call rejection, and cancels a local job when that provider is configured. It records desktop and 390px mobile screenshots, a browser video, exported JSONL, and a machine-readable report in `artifacts/qa`. After a successful run it retains only the latest QA video and downloads. No remote model calls are made. The QA runs and cancelled job remain in local API history as recorded evidence.

Set `WORLD_ENGINE_UI_URL` to run the same checks against another local preview address. Browser errors fail the check. Tables intentionally scroll horizontally at narrow widths; the document itself must not overflow.
