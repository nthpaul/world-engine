# Native Controls QA Results

The first connected controls check found a real narrow-screen defect despite
passing its automated assertions. Its original evidence is preserved. A reviewed
layout correction and stronger child-button bounds check then passed fresh
connected QA and independent visual inspection. Neither phase submitted a
rollout or ran inference.

## Two Separate Receipts

| Receipt | Controller / API Startup | Automated Checks | Visual Acceptance | Original Files / Bytes |
| --- | --- | --- | --- | --- |
| [20261010-v1](../artifacts/native-controls-qa/20261010-v1/report.json) | `8b82c7aa5ac944ec35b62ef2d12f28f4b8d254cb` | 15 passed | Failed: clipped Start button at width 360 | 14 / 1,782,398 |
| [20261010-v2](../artifacts/native-controls-qa/20261010-v2/report.json) | `6bdec4f0281e51d502c505bda502ae5fe0c3dd2a` | 15 passed | Accepted: complete Start and Cancel footer | 14 / 1,784,739 |

The v1 capture checked document overflow and dialog bounds, but did not check that
the footer buttons fit inside that dialog. Root and console independently saw the
clipping. The source51 correction uses a scrolling dialog body with nonshrinking
header and footer. New assertions check both buttons' full bounds. V1 remains
**15 automated checks passed, visual acceptance failed**, not an overall pass.

Each phase captured twelve screenshots across 1440x960, 390x844 and 360x844.
The corrected [360-pixel native ledger view](../artifacts/native-controls-qa/20261010-v2/360-local-tools-ledger-defaults.png)
shows complete buttons. Root reviewed all twelve screenshots in each phase,
including full narrow views; there were no incoherent overlaps or body-scroll
issues in v2. Internal body scrolling is intentional.

## What Was Verified

- Legacy dialog concurrency starts at 4 with editable evaluation-only controls.
- Either native alias starts at 1, selects `qwen3:8b`, locks evaluation-only true
  and exposes no paid consent control.
- Explicit concurrency 2 persists when switching between native aliases.
- Legacy local concurrency and evaluation-only remain editable.
- Every dialog closes with Cancel. Start is never pressed.

One worker is a conservative native default, not an optimality claim or hard cap.
Both real phase receipts record 24 GETs: sixteen UI assets and two each for health,
providers, environments and run list. There were no blocked requests, browser
errors, forwarded mutations, new rollouts, imports, downloads or inference
requests. Two development WebSockets were suppressed in each phase.

The catalog projection contains only the two native alias IDs, local/configured
and opt-in flags, and a boolean confirming the exact public model name exists.
No full catalog, other installed model names, remote configured flags, keys or
daemon bodies are published. This readiness check does not verify a model digest
or attest weight execution.

## Independent Proof

The [additional validation sidecar](../artifacts/native-controls-qa/20261010-v1/independent-validation.json)
records both original manifests and source hashes. Root and console checked all
28 original files, totaling 3,567,137 bytes. Each phase's 31 recorded source hashes
matched its committed blobs and the current bytes at its own audit time. V2's
pre/post source manifests were identical. Source scope was clean while overall
checkout dirtiness was reported truthfully for out-of-scope artifacts.

Both complete videos decoded successfully with `ffmpeg -v error -xerror`. Root
also inspected three early/middle/late frames per phase. The VP9 recordings are
1440x960, lasting 2.80 seconds in v1 and 2.68 seconds in v2. Gray mobile
letterboxing in the fixed-size recording is intentional. Collector elapsed times
were 2.254 and 2.135 seconds; these are descriptive QA timings, not performance
measurements.

API startup revision and process identity are separate operator attestations:
source50 started at 11:24:58 UTC with PID 33196; source51 started at 11:37:44 UTC
with PID 74741 on 2026-10-10. Package health version `0.1.0` is not a commit proof.
Root's read-only SQL checks found integrity `ok`, thirteen runs, seventy episodes
and no active jobs before and after the final read-only UI phases. The two added
episodes came from the separately authorized source50 API smoke, not controls QA.

Original reports, screenshots and videos were not changed. This guide and the
sidecar are later publication files, excluded from original file/byte totals and
collection quotas. The published-artifact cap is not a hard transient video disk
quota, and browser deadlines/cleanup remain cooperative.

## Related Evidence

The two original native API smoke episodes retain source50 provenance. Their
later read-only inspector QA used source51 and preserved the original envelope,
numeric types, usage, termination and provenance; it generated no new inference.
Those episode/export/Harbor proofs are separate from configuration acceptance.
See the [API smoke protocol](native-api-smoke-protocol.md) and
[controls protocol](native-controls-qa-protocol.md) for their boundaries.
