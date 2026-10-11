# Scripted CPU Profiling

`scripts/profile_scripted.py` is a rerunnable profiling lever, not a model benchmark or a causal speedup experiment. Its default is a pure plan: no episodes, profiler, database, source commands, model transport, API or Docker activity.

```sh
uv run python scripts/profile_scripted.py --plan
```

## Reviewed Collection

Run only after review, source commit, CI and explicit collection authorization. Use a full lowercase reviewed SHA and a new output path. Existing files, directories and live or dangling symlinks fail before source work. The collector never overwrites prior evidence.

```sh
uv run python scripts/profile_scripted.py --collect \
  --source-revision <reviewed-full-40-character-sha> \
  --output artifacts/profiling/<new-run-name>
```

The source gate covers all runtime Python files, `pyproject.toml`, `uv.lock`, this collector, its tests and this guide. HEAD must equal the requested revision; that scope must be committed and clean. Individual source hashes and a separate full-checkout dirty flag are retained. The same gate runs between worlds, before replay/persistence and at finalization. Historical profiling inputs are hash checked, not modified. No credentials or provider catalog are read.

The original producer remains accessible at [producer.py](../artifacts/profiling/20261010-v1/producer.py). It is a retrospective publication sidecar of an ad-hoc command executed at `d71a05d35f8c95df930d957ff4ebecc2ef3b0b72`, not a collector that had been committed or predeclared before that run. Its original report, Markdown, raw trace and producer hashes are retained separately. Adding this lever does not change those bytes or retroactively add sidecar bytes to the original collection total.

## Fixed Workload

The world order is CRM merge, refund operations, incident control, access provisioning. Each world uses seeds `0..23`, the scripted reference policy, concurrency one, at most 20 decisions and a 30-second episode timeout. All episodes are evaluation-only and training-ineligible. There are no model, network, paid-provider or Docker calls.

For each world, run 24 episodes unprofiled first, then the same 24 episodes under cProfile. Both trials retain full-width envelopes: protected operator snapshots, trusted grades, public observations and controller contexts. Every JSONL wrapper labels the world, trial and index. A successful receipt has **192** envelopes, unlike the original receipt's 96 profiled-only envelopes. The collector checks both trials' scenario identities, actions, initial/final state and grade for agreement; timing and generated episode IDs are not compared.

Output serialization and fsync occur after each 24-episode timed block. Completed episodes from an interrupted block are saved in its finalizer. This is not mid-block crash durability. Serialized envelopes are saved before workload checks. An envelope that cannot serialize or fit the remaining cap gets a bounded generic diagnostic instead; its slot is not counted as a persisted full episode. Returned envelopes that remain unwritten when a later write fails are explicitly counted. The collector stops without retrying.

The measured replay phase replays only the **96 profiled** episodes, matching the original producer. The unprofiled envelopes are also available for separate independent replay proof; do not describe the 96 measured replays as proof of all 192.

Persistence phases use a fresh `TemporaryDirectory` SQLite database, never the API or primary database: four 24-episode runs, 96 profiled-episode appends, 100 list operations returning four runs, and 40 CRM detail operations containing 24 episodes. The list and detail phases follow completion of those runs. Temporary data is removed even if an operation fails.

## Observation Counts

Counts come from the exact `observe` method code identity in the per-world cProfile statistics. They do not sum every function named `observe`, wrap the method, or add counter-only episodes. Unprofiled reads are not instrumented. Factory reset reads are included.

| World | Decisions Per Trial | Setup Reads Per Episode | Historical Reads | Current Expected Reads |
|---|---:|---:|---:|---:|
| CRM merge | 152 | 3 | 528 | 376 |
| Refund operations | 64 | 3 | 264 | 200 |
| Incident control | 192 | 3 | 648 | 456 |
| Access provisioning | 320 | 4 | 1,056 | 736 |

The historical formula is `3 * decisions + setup_reads_per_episode * 24`; the current formula is `2 * decisions + setup_reads_per_episode * 24`. Access has four setup reads, not three. These counts test the removal of one public observation read per decision. They do not establish a causal throughput gain. A workload or observation-count mismatch stops collection after preserving returned evidence.

## Bounds And Interpretation

The aggregate deadline is 240 seconds, with 15 seconds reserved for final checks, public machine metadata and report output. Async timeout and monotonic guards cover trusted work; synchronous Python, filesystem operations or cancellation-suppressing extensions are not hard-killed. An overrun is recorded as a stopped collection. This is not a hostile-code sandbox.

All published files together are capped at 64 MiB, including raw JSONL, eight binary profiles, eight top-50 text profiles and the report. One MiB is reserved for the report, with small diagnostic headroom. Files are created exclusively. This artifact cap does not bound process memory or temporary SQLite/profile storage. A successful receipt preserves all 192 episodes; the cap does not justify claiming complete evidence if the collector stops early.

`profile.json` records requested/attempted/persisted/unattempted slots, partial blocks/phases, source and historical-input hashes, raw SHA256, exact artifact bytes, runtime/machine metadata, actual phase durations and structured top-50 cumulative/exclusive statistics. A stopped receipt retains available evidence but is not a successful complete run. Secrets and exception object representations are not written into diagnostics.

Comparison with the historical run is descriptive. Trial ordering, cold caches, collection-revision introspection, shared-machine load and cProfile overhead are uncontrolled. This committed lever also adds deadline and artifact guards that the original ad-hoc command lacked. Nested cumulative profile timings are not additive. Four 24-episode workloads and one 24-episode CRM detail workload do not establish large-history or 100-episode server performance, cloud inference throughput or competitor superiority.

## Offline Verification

```sh
uv run pytest -q tests/test_profile_scripted.py
uv run ruff check scripts/profile_scripted.py tests/test_profile_scripted.py
```

These tests mock rollout, semantic replay, profiler statistics, Store and source commands. They verify the collection protocol and failure accounting, not actual timing or world correctness. Actual profiling remains a separately authorized collection against committed source.
