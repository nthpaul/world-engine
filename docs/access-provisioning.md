# Access Provisioning

`AccessProvisioning` is a synthetic partial-observation world using the existing `Environment` lifecycle. It models one assigned request, bounded directory and group discovery, service-issued reviews, least-privilege grants and justified denials. There is no external directory, real reviewer, SCIM implementation or compliance claim. The Python object is trusted in-process simulation, not isolation against hostile extensions or the host.

## Observation and Discovery

`reset(seed)` and `observe()` expose the assignment, role, task, logical tick, tools and only the current bounded tool result. They do not expose the private directory, group catalog, membership history, approvals, expected outcome or grader. Queue and catalog pages are static, sorted by immutable IDs, 1-based and at most two items. Each capability has three matching groups. Request IDs must be found in the queue; employee IDs must be returned by search; policies require a discovered group. `get_manager` resolves the directory's immutable link after the employee detail read, never an agent-supplied reviewer.

The request's staff number and email must be searched independently. Staff numbers match exactly; emails are trimmed and lowercased. Both searches must return the same unique employee. Display-name prefix search is available but cannot replace this evidence. Duplicate names are intentional. Query receipts record actual returned IDs, so an empty out-of-range exact query is not sufficient evidence.

`snapshot()` is a separate trusted-operator view containing the full synthetic state. Discovery receipts, current view and successful-operation journal are in that state, covered by rollback and replay hashing. Normal provider observations and SFT contexts never copy that snapshot. Discovered public rows remain visible in recorded history; partial observation is not a promise that a successfully navigated row will later disappear from model context.

## Settlement Rules

Denial precedence is identity conflict, inactive employee, invalid manager, then department policy denial. Closure first requires the discovered facts for its reason and rejects missing evidence generically; guessing denial labels cannot reveal an unobserved answer. A valid identity requires reading all candidate policies. Choose an allowed group by extra capability count, risk rank and immutable group ID. Broad admin hints and request justification are untrusted on both positive and denial cases.

Reviews are deterministic synchronous services, not actual people. Each record binds request, employee, group, policy version, stage, selected approver, decision and issue/expiry ticks. Stages are manager, finance and optionally security. The service does not accept an approver, verdict or TTL from the agent. Every mutating service action uses `tick + 1`, since the base environment advances the logical tick after the action. Review validity is `issued_tick <= grant_tick < expires_tick`; lifetime is eight ticks. Grant receipts retain the exact review IDs and grant tick. Later diagnostic ticks do not invalidate an already authorized grant.

An identical valid review retry returns the original record without another event. An expired review is renewed without deleting old history. An identical grant-key retry returns its receipt even after closure and expiry, but only before `finish`; a different key cannot create another grant. Closure retries do not duplicate events. Denied operations preserve the complete operational state and advance the base logical tick. Finishing ends tool access.

## Cases and Budget

`seed % 8` selects four positive cases and four denials:

| Case | Fixture | Settlement |
|---|---|---|
| 0 | Normal finance read | Grant |
| 1 | Duplicate display names | Grant for matched immutable ID |
| 2 | Staff/email conflict | Deny identity conflict |
| 3 | Inactive employee | Deny inactive employee |
| 4 | Payout write, three review stages | Grant |
| 5 | Private expired and wrong-group prior reviews | Service issues fresh exact reviews, then grant |
| 6 | Prohibited department with broad hint | Deny policy |
| 7 | Inactive or self manager | Deny invalid manager |

The reference policy uses only public observations and successful tool history. Case 5 tests service-history preservation and renewal boundaries; its prior reviews are private, and its policy decision path is the same as normal provisioning. It is not measured agent recovery from an observed failure. Worst-case case 4 takes exactly 19 decisions including `finish`: three queue pages, request read, two independent identity searches, employee and manager reads, two group pages, three policy reads, three reviews, grant, close and finish. The usual 20-step budget has one spare decision; arbitrary failed actions and delayed renewals are not promised to fit that budget.

## Trusted Evaluation

Evaluation rebuilds the seeded fixture from the implementation rather than trusting changed current fields or a self-reported outcome. It independently validates journal certificates and reconstructs discovery projections, reviews, grants and closure without invoking service `apply`, `step`, rollout or reference policy. It verifies complete operational-state equality and original eligibility, exact selected group, approval scopes and lifetime, and grant-time review validity. Explicit guards remain active under optimized Python. Any changed role, directory, policy, prior history, unrelated request, discovery receipt, current view, journal or grant certificate receives zero reward. Individual checks report diagnostic progress, but outcome reward is binary: one only for a safe, correctly settled, explicitly finished request; zero for all incomplete or unsafe work. Early finish and repeated inspection receive no reward.

This verifies state and service-journal coherence, not collection authenticity against a malicious controller that can fabricate an entirely consistent alternate history. There is no hidden signing key, external authority or concurrency/revocation model.

## Run Controls

Use the normal SDK or CLI:

```sh
uv run python -m world_engine --db /tmp/access-example.sqlite3 rollout \
  --environment access-provisioning --provider scripted-oracle --episodes 8 --seed 0 --evaluation-only
uv run pytest tests/test_access_provisioning.py -q
uv run python examples/access_provisioning.py --source-revision FULL_REVIEWED_COMMIT_ID \
  --cycles 1 --output artifacts/access-provisioning/controls.json
```

The collector requires an explicitly reviewed full source revision, a clean complete `src/world_engine` runtime, dependency files and owned collector/test/docs, and a fresh output path before running episodes. Fixed seeds cover the eight cases for one to four cycles, with two scripted policies, 20 steps, 30 seconds and concurrency one. It refuses episodes over 1 MiB or receipts over 16 MiB, never silently truncates, and prints only a brief output summary. It performs free scripted outcome controls and replay verification, with full evaluation-only operator records, source fingerprints and `training_eligible=false`. Collect only after source commit. These controls are not a local-model study and do not retroactively extend the previous three-world benchmark.

Conceptual source links and the design's explicit synthetic choices are recorded in [the frozen proposal](access-provisioning-proposal.md). No enterprise data, task package or vendor implementation is copied.
