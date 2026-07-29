# Agent log: poincare

**Role:** stage 4 independent read-only reviewer of the integrated agent rung (`PLAN-agent.md`)
**Completion status:** done

## Assignment

Independent review of the whole agent-rung build in `prototypes/failure-to-intervention`
(commits ff3250c, 57bd7ad, 464037e, 7211a72 over d210be9), not any single stage. Check
PLAN-agent compliance line by line, frozen files, bugs in `src/agent/`, test quality,
docs accuracy, scope creep. Own only this log. Modify nothing, commit nothing, no live
model calls, no network.

## Decisions

- **Ran my own end-to-end harness instead of trusting the suite.** A throwaway tsx
  script in /tmp (deleted after) ran `runAgentEvaluation` k=3 with a scripted mixed
  provider (flaky-once pass, double-failure excluded, clean pass) into a temp
  episodesDir, then `aggregateEpisodes` over it, and printed the full built prompt for
  `original-incident`. Every number matched the builders' claims exactly (runner
  `infraRetries` 1 vs audit 2, passRate 1 over denominator 2, cost $0.021 from exact
  price math, 3 flattened infraErrors with file paths).
- **Refined godel's "lost usage" framing.** A retried infrastructure attempt loses no
  *observable* token usage: on the retry path `complete()` threw, so no usage exists to
  record. Cost accounting is complete for what the client can observe. Not a defect.
- **Judged the runner-vs-audit `infraRetries` naming difference a minor, not a
  blocker.** Both definitions are deterministic and each is defensible in isolation
  (recovered-only vs all-retried). But `demo:agent` prints the runner number while
  `audit-data.json` carries the audit number under the *same field name*, and the only
  pin is a comment in `tests/agent-redteam.test.ts` — a file the AUDIT author may never
  open. Renaming the audit-side field (e.g. `episodesRetried`) any time before AUDIT.md
  is authored costs nothing (the value is derived from transcripts, not stored in them).
- **Read the plan's "not this rung" line as stale, and the build's choice as correct.**
  d210be9 added the five-provider design (file list, provider rules, acceptance 7) but
  never removed "local/Ollama drivers" from "Explicitly not this rung". The plan
  contradicts itself; the build followed the more specific, later amended sections.
  Correct call. The plan document wants a one-line cleanup.

## Evidence

Commands I ran myself (not quoted from logs): `git log`/`git diff --stat d210be9..HEAD`,
`pnpm test` → **179/179 across 6 files**, `pnpm typecheck` → clean, `pnpm demo` →
pinned matrix unchanged, `pnpm demo:agent` with no keys → clean one-line error naming
`ANTHROPIC_API_KEY`, exit 1; `PROVIDER=bogus` → clean error listing the five valid
names, exit 1. My /tmp harness (above). A `git status --porcelain` over the prototype →
empty (no smoke artifacts left behind). Grep over `src/agent/` for TODO/FIXME/stub →
none.

### Frozen files (acceptance 2)

`git diff --stat d210be9..HEAD` over `src/verifier.ts`, `failure_trace.json`, `cases/`,
and the four pre-existing test files (`reconstruct`, `verifier`, `interventions`,
`redteam`) → **empty**. `src/report.ts` diff is import additions plus the appended
`runAsyncEvaluation`; the `runEvaluation` body including the thenable guard is
byte-identical in the diff.

### Prompt calibration (the experiment)

Read `src/agent/prompt.ts` and eyeballed the full rendered prompt for
`original-incident`. IN: normalization rule, canonical = earliest `created_at`, genuine
dup = same number + amount among **non-void** copies (matches `verifier.ts:45`
`status !== "void"` exactly — PLAN.md's looser "active copies" wording is not what the
verifier implements, and the runbook tracks the verifier), survivor rule, void is not
transfer, deactivate never delete, the exact audit-event schema with all six details
keys. OUT: no pair ids, no dup-invoice id, no "expected" anything, no mention of the
verifier or invariants (also test-pinned). The only case-specific text in the prompt is
the state JSON itself, which is input, not answer. **Calibration is clean.**

### Findings

**Blockers:** none.

**Majors:** none.

**Minors:**

1. `WALKTHROUGH.md:302-334` — the tests/ section lists five test files; there are six.
   `tests/agent-redteam.test.ts` (61 tests, a third of the suite) has no bullet. The
   file landed in 7211a72 after sagan's docs pass in 464037e and nobody circled back.
   The doc's own title promises "every file, in reading order".
2. `src/agent/audit-report.ts:111` vs `src/agent/runner.ts:139` — same field name
   `infraRetries`, two definitions: runner counts recovered episodes only; audit counts
   every transcript with `attempts > 1` (adds double-failures). `demo:agent` prints the
   runner number, `audit-data.json` carries the audit number. Deterministic and
   test-pinned (`tests/agent-redteam.test.ts:635-640`) but pinned only in a test
   comment. Rename the audit-side field before AUDIT.md is authored.

**Notes:**

3. `PLAN-agent.md:176` — self-contradiction: "local/Ollama drivers" sits under
   "Explicitly not this rung" while the file list and acceptance 7 require the ollama
   driver. Stale leftover from before d210be9; the build followed acceptance 7, which
   is right. Plan doc wants one line of cleanup.
4. `src/agent/prompt.ts:38` — the runbook omits the canonical tie-break (lowest id on
   equal `created_at`) that `verifier.ts:38` implements. I checked all four seeds: no
   pair has tied `created_at`, so it cannot bite these cases. Worth adding if new cases
   are ever seeded.
5. `src/agent/prompt.ts:78-82` — template slots are sequential `String.replace` calls.
   A future case whose objective/constraint/state text contained a `{{SLOT}}` marker
   would collide (or worse, a state value containing `{{OUTPUT_SCHEMA}}` would eat the
   real slot). I grepped all four frozen seeds: no `{{` anywhere. Latent only.
6. Acceptance 7 literal wording ("`createProvider` instantiates each with a mocked
   transport") is split rather than direct: `createProvider` (`providers/index.ts`) has
   no injection seam, so tests exercise the five factories with mocked transports and
   `createProvider` separately with dummy keys (construction only, no `complete()`).
   env-key wiring IS covered through `createProvider` missing-key tests; the one
   untested construction path is openrouter's `baseURL` override
   (`providers/openrouter.ts:6`), which an injected client bypasses. Spirit met.
7. `providers/cursor.ts` silently ignores `temperature`/`maxTokens`;
   `providers/ollama.ts` ignores `maxTokens` (no `num_predict`). Irrelevant to the
   anthropic acceptance run; undocumented in README/WALKTHROUGH except cursor's usage.
8. `audit-data.json` is not gitignored and its commit/ignore status (hamilton's open
   question) was never decided. Harmless until the live run creates one.
9. `src/agent/config.ts:18` — no range check on `temperature` (a hand-edited `5` would
   surface as provider 400s → infrastructure → excluded, not a config error). Committed
   file pins 0, so inert.
10. Mid-run crash (e.g. `writeTranscript` throws) leaves a partial episode set that
    `audit-report` would aggregate as-is; failures are loud, not silent. Acceptable.
11. `classifyEpisode` maps a plain `Error` from a driver bug to `infrastructure`
    (godel pinned this). With k=10 a systematic bug yields passRate `null` — visible,
    not maskable. Agree with the pin.
12. Precedence verified mutually-consistent: `providerError → malformed → invalid-action
    → business-violation → pass` is the only sensible order given untouched/partial
    state always violates; end-to-end pins exist (e.g. `agent-redteam.test.ts:246`).
    Abort indexing (`driver.ts:144-155`) carries true plan indices; no off-by-one.
    Whole-plan Zod validation before execution matches PLAN-agent's
    "validates every call, then executes in order".

### Test quality

Both suites assert behavior, not implementation shape: state-level abort proof
(`agent.test.ts:184`), digest-level fresh reconstruction, on-disk transcript schema +
key-grep, exact cost math to 10 decimal places, aggregation over real files.
`classifyEpisode`'s unit matrix restates the if-chain — inherent for a pure
five-way function — and the precedence pin was mutation-tested by archimedes; the
end-to-end precedence is covered in the red-team file. No tautologies found. Every
pinned area from acceptance 1 (plan-schema, abort-on-invalid, classification, runner
via fake driver, no network) and acceptance 7 (five drivers, mocked transports, clear
misconfiguration errors, no fallthrough) has at least one behavioral test.

### Docs accuracy (spot-checks, all against code I ran or read)

1. `.gitignore` = `node_modules/` + `episodes/` — README/WALKTHROUGH correct.
2. Script names `demo`, `demo:agent`, `test`, `typecheck` — correct.
3. Env var names (`ANTHROPIC_API_KEY` etc., `PROVIDER` override) — correct in both docs.
4. WALKTHROUGH's "missing API key exits with one clean line naming the env var, not a
   stack trace" — verified by running it (two providers + bogus name).
5. README's taxonomy/k=10/temp-0/pinned-snapshot claims — correct (`K = 10` in
   `demo-agent.ts:13`, `agent.config.json`).
6. WALKTHROUGH's cursor odd-one-out claims (empty temp cwd, no token usage) — correct.
7. WALKTHROUGH's `agent.test.ts` bullet (written before the file existed) — accurate
   against the real file. The one doc gap found is minor finding 1 above.

### Scope creep

None. The file tree matches PLAN-agent's list exactly. No multi-turn loop, no second
model, no MCP, no UI, no extra domains, no difficulty escalation. All five drivers are
fully implemented — no stubs or fakes in `src/`. The injected test seams are an
orchestrator-pinned design decision, not leftover scaffolding.

### Acceptance criteria verdict

1. **Met.** 179/179 green, typecheck clean, pinned areas covered, no network (all
   provider tests inject; the ollama default-fetch path never runs in tests).
2. **Met.** Zero-diff verified on every frozen path (above).
3. **Ready (cannot be met without the user's key).** Every non-live piece verified:
   matrix print with agent column, classification counts, token/cost totals,
   falsification rules printed, transcripts written per episode, clean exit-1 paths.
   Only the API call itself is unexercised.
4. **Met.** No key-material path into transcripts: only `kind`+`message` cross the
   provider-error boundary; SDK error bodies don't echo keys; tests grep transcripts
   with four distinct dummy keys; my own grep clean.
5. **Mostly met.** README section complete and accurate; WALKTHROUGH covers every new
   file except `tests/agent-redteam.test.ts` (minor finding 1).
6. **On track.** `PREDICTIONS.md` committed in ff3250c, the first build commit, before
   any live run (no key in the environment, no `episodes/`, no `AUDIT.md` — verified
   absent). AUDIT.md correctly does not exist yet. `audit-data.json` regeneration from
   `episodes/` verified through `aggregateEpisodes` on my own synthetic run.
7. **Met in spirit.** Five drivers behind `ProviderDriver`; mocked-transport tests per
   factory; `createProvider` resolution + env-key wiring tested; misconfiguration fails
   loud, never falls through. Literal wording split (note 6).

## Files changed

### Created

- `coordination/agents/poincare.md` (this file)

(Scratch harness `/tmp/poincare-check.ts` was created, run, and deleted; never in the
repo. Nothing else touched.)

## Unresolved questions

- For the orchestrator/user before the live run: rename audit-side `infraRetries`
  (finding 2) and add the missing WALKTHROUGH bullet (finding 1)? Neither blocks the
  run; both matter most when AUDIT.md is authored.
- `audit-data.json`: gitignore it or commit it alongside AUDIT.md? Still undecided
  since hamilton's log.
- PLAN-agent.md line 176 ("local/Ollama drivers" under "not this rung") — stale after
  d210be9; worth a one-line plan amendment for the record.

## Completion status

done — the build is compliant and **ready for the live run**. Two minors (docs gap,
field naming) are cheap pre-run fixes but neither invalidates anything the run produces.
