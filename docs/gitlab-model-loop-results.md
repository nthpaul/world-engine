# Browser model loop investigation

The original New project loop had a model error and a harness defect. The model
chose unrelated navigation. The old context then discarded public transitions
and saturated into identical requests. The repaired context is merged in
[PR77](https://github.com/nthpaul/world-engine/pull/77), but the fresh model
attempts still failed. Reference success is not model success.

## Original failure

At source `9901b26b488173ca3dfd4269e5c10b71475b7840`, attempt
`642ee1fd-0079-4b55-92d7-4978a8142a1a` made thirty valid browser actions. It
clicked New project once, then its self-referential breadcrumb twenty-nine
times. The current accessibility tree and task were present; node mapping and
native action parsing were correct. The visible Member tab offered a route to
the assigned project, but the model did not use it.

The old request kept only twelve actions and execution acknowledgements, without
their post-action observations, absolute steps or remaining budget. Decisions
fourteen through thirty sent byte-identical requests. An execution result
`ok: true` established that the click ran, not that the task progressed.

## Versioned repair

Protocol `ollama-browser-tools-v3` preserves normalized accepted native tool
calls, their public results and linked post-action observations. It supplies
absolute decision numbers, remaining actions and unchanged-observation feedback.
Older observations have explicit bounded summaries; the current observation is
retained. The console displays the complete recorded native request.

Model preparation verifies local identity and records digest, template hash and
daemon version. `/api/show` metadata has a separate 256 KiB bound; generation
responses remain bounded at 64 KiB. HTTP connect/write/pool limits are ten
seconds; read is `min(episode_timeout, 180)`. The existing outer episode deadline
can cancel earlier. Typed redacted transport failures retain elapsed time and
the exact received prefix. Client closure does not certify daemon closure.

Task, fixtures, grader, ordinary-user permissions, reference behavior and native
generation options stayed unchanged. No task hints or forced correct actions
were added. Source was reviewed and committed before each experiment; the API
was restarted from a matching immutable checkout before each real cohort.

## Retained diagnostics and real runs

These are separately declared local samples, not a capability benchmark or an
isolated causal comparison. Every failed sample remains retained.

| Collection | Actual result |
| --- | --- |
| Diagnostic v1, `53ff12df` | Both 8B contexts selected the same breadcrumb; 32B metadata exceeded the old bound before inference; final cell unattempted |
| Diagnostic v2, `241fd236` | Four calls completed without executing actions; corrected 32B selected Create blank project, still off-task; other cells repeated the breadcrumb |
| Real v8, `241fd236` | Four controls qualified; dense 32B made three valid clicks, then `provider_error` on a fourth request without a complete reply; reward zero |
| Real v9, `3d6c4860` | Four controls qualified; cached 30B mixture-of-experts model made nineteen actions, ten invalid, then the outer ten-minute timeout; reward zero |

V8's old failure recorder retained no exception category. Its roughly
ninety-second empty-prefix failure cannot independently identify the precise
timeout type. V9 changes both model and transport, so it does not isolate either
factor's effect. No download, paid call, cloud resource or training was used.

## Real v9 evidence

Source: `3d6c4860896d9cc658d4dc4f9243f16f6d11430b`.
Task: `gitlab-incident-triage` 1.0.2, grader `gitlab-triage-state-v3`.
Model: cached `qwen3:30b-a3b`, Ollama 0.22.0, native tools v3.
Generation: temperature zero, 512-token prediction cap, 16,384 context, thinking off.
Model budget: seed42, thirty actions, 600 interaction seconds, no automatic retry.

| Slot / local attempt | Actions / invalid | Termination | Reward |
| --- | ---: | --- | ---: |
| Incomplete `aa1e9af9-bd2e-4a06-8162-1a885136e318` | 1 / 0 | finished | 0 |
| Changes required `d259d3f4-42af-47b4-b907-5cc187b41657` | 15 / 0 | finished | 1 |
| Already correct `2691ed11-7849-42e9-92ba-8bb2d1e6fe83` | 15 / 0 | finished | 1 |
| Close compatibility `105875e4-486c-493e-8649-e5df53efd2a3` | 14 / 0 | finished | 1 |
| Actual model `4e28b496-4043-4899-8433-790ee0d3c006` | 19 / 10 | timeout | 0 |

Open the [actual model trace and outcome](http://127.0.0.1:5173/#attempts/4e28b496-4043-4899-8433-790ee0d3c006)
or the separate [successful reference](http://127.0.0.1:5173/#attempts/d259d3f4-42af-47b4-b907-5cc187b41657).
These links require this operator's retained local database, not a fresh clone.

The model created a new project rather than finding the existing incident
project. It then opened a project-transfer dialog and repeatedly clicked the
background Actions button despite current observations showing the modal and
its Close and Cancel controls. Those clicks failed with
`browser_action_failed` and uncertain effects. That node remained current and
visible in each corresponding observation. The recorder lacks the underlying
browser exception category, so these are not proven stale-node or click-timeout
failures. All twenty model request hashes are distinct; linked error results,
stagnation feedback and changing budgets were supplied. The old byte-identical
context defect did not recur. The model still failed to recover.

The final inference was cancelled by the outer deadline after 9.177 seconds,
with no response status or body. Nineteen complete raw replies report 235,328
input tokens and 437 output tokens; the last request's usage is unknown.
These counts are not exact sampled-token or behavior-probability records.

All seven isolated model checks rejected the state. Browser/video closure
returned before state sealing, followed by separate grading and completed
cleanup. Its seal hash is
`ae353ab4098ad32e61e01b3fbcb06466bf50cf8542bab3da10624d1827b4d1d0`.
The cohort took 1,549.816 seconds; model startup took 149.808 seconds,
interaction 600.024, browser closure 8.496 and sealing 28.718.

The independent selected-state diff finds an extra project, namespace,
membership and feature row. Prior selected rows stayed unchanged, but the extra
records violate preservation. The assigned incident remains unassigned, without
the severity link or required certificates. The zero grade agrees with the
standalone verifier; it was not weakened to accept this off-task work.

Independent evidence review verified 1,774 original files / 417,869,688 bytes,
45 source blobs, 844 saved API body pairs, 456 journal records and 74 registered
media artifacts. Every request rebuilds from public inputs. Prior cohorts and
both diagnostics remain unchanged. A separate root check preserves all thirty-two
prior browser rows, 520 operator files and the unchanged legacy database.

## Terminal media QA

Read-only console QA passed 42 reference checks, 46 actual-model checks and
20 full-request inspection checks at desktop, 390px and 360px. Twenty-five
screenshots were reviewed. The final recorded native request is 55,850 canonical
bytes with forty-one messages; the complete rendered JSON values match at all
three widths. Prettified JSON is not claimed to be byte-identical wire encoding.

Desktop playback advanced for both actual rollout videos. Four complete video
decodes and twelve sampled-frame checks passed for rollout and console footage.
Mobile playback remains unqualified. Known full-page mobile fixed-navigation
compositing and the broad `issue_preservation` diagnostic wording remain limits.
QA made 169 HTTP GETs and three scoped development HMR connections, with no
POST, blocked request, new attempt or inference. Media stays in the private
operator evidence store; the local attempt links expose the registered images
and actual videos. Reference footage is always labeled separately.

## Interpretation and limits

The repair removes confirmed information loss, not the model's inability to
select the right workflow. There is no demonstrated task rescue, learning gain,
general success rate or architecture-level latency advantage. Screenshots and
videos are operator evidence; this text adapter receives public accessibility
observations, not image pixels. Browser evidence remains evaluation-only and
excluded from training exports.

This local Docker/host-browser pilot grades selected GitLab tables. It is not
full application fidelity, tenant-safe isolation or host authenticity proof.
Keep provider failures, invalid actions, deadline truncation, state rejection
and resource cleanup distinct. Do not convert a failed model run into a pass
by substituting reference footage or modifying its original grade.
