import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { loadCases, type CaseFile } from "../src/cases";
import { loadAgentConfig, type ProviderName, type ResolvedAgentConfig } from "../src/agent/config";
import { PlanSchema } from "../src/agent/plan-schema";
import { extractPlanJson, runAgentEpisode } from "../src/agent/driver";
import { runAgentEvaluation, TranscriptSchema } from "../src/agent/runner";
import { aggregateEpisodes } from "../src/agent/audit-report";
import { createProvider } from "../src/agent/providers";
import { createOllamaDriver } from "../src/agent/providers/ollama";
import { ProviderCallError, type CompletionRequest, type ProviderDriver } from "../src/agent/providers/types";

// Red-team pins for the edges tests/agent.test.ts does not cover. No network:
// every episode runs through scripted ProviderDrivers or injected seams.
// Three earlier FINDING tests (retried-attempt visibility, infrastructure error
// detail, stale smaller-k transcripts) were fixed in src/agent and are now
// permanent passing assertions of the fixed behavior.

const cases = loadCases();
const byId = new Map(cases.map((cf) => [cf.trace.case_id, cf]));

function getCase(id: string): CaseFile {
  const cf = byId.get(id);
  if (!cf) throw new Error(`case ${id} not found in loadCases()`);
  return cf;
}

const REASON = "duplicate customer merge";

const config: ResolvedAgentConfig = {
  provider: "anthropic",
  model: "test-model",
  temperature: 0,
  maxTokens: 1024,
};

const REQUEST: CompletionRequest = { prompt: "hello", model: "m", temperature: 0, maxTokens: 64 };

afterEach(() => {
  vi.unstubAllEnvs();
});

const scriptedProvider = (text: string): ProviderDriver => ({
  name: "scripted",
  complete: async () => ({ text }),
});

// Correct single-shot merge of the original incident's pair (same shape as
// tests/agent.test.ts uses): void dup invoice 2, move ticket 1, deactivate
// customer 2, write the merge audit event.
const CORRECT_PLAN = JSON.stringify({
  calls: [
    { method: "voidInvoice", invoiceId: 2, reason: REASON },
    { method: "transferTicket", ticketId: 1, toCustomerId: 1 },
    { method: "deactivateCustomer", customerId: 2, reason: REASON },
    {
      method: "writeAuditEvent",
      action: "customer.dedup.merge",
      entityType: "customer",
      entityId: 2,
      details: {
        canonical_customer_id: 1,
        deactivated_customer_id: 2,
        transferred_ticket_ids: [1],
        transferred_invoice_ids: [],
        voided_invoice_ids: [2],
        reason: REASON,
      },
    },
  ],
});

describe("extractPlanJson (red-team edges)", () => {
  it.each<[string, string]>([
    ["uppercase ```JSON tag", '```JSON\n{"calls": []}\n```'],
    ["non-json language tag", '```typescript\n{"calls": []}\n```'],
    ["trailing comma in bare JSON", '{"calls": [],}'],
    ["empty response", ""],
    ["whitespace-only response", " \n\t "],
  ])("malformed: %s", (_label, raw) => {
    // All of these fail the bare parse and match zero lowercase-```json fences.
    // Matches the documented rule (full-text parse, then exactly one fenced
    // block); the prompt forbids fences anyway, so strictness is acceptable.
    expect(() => extractPlanJson(raw)).toThrow(/0 fenced code blocks/);
  });

  it.each<[string, string]>([
    ["trailing spaces on the opening fence line", '```json   \n{"calls": []}\n```'],
    ["trailing spaces after the closing fence", '```json\n{"calls": []}\n```   '],
    ["indented closing fence", '```json\n{"calls": []}\n  ```'],
    ["CRLF line endings", '```json\r\n{"calls": []}\r\n```'],
    ["BOM-prefixed bare JSON", '\uFEFF{"calls": []}'],
  ])("tolerated: %s", (_label, raw) => {
    expect(extractPlanJson(raw)).toEqual({ calls: [] });
  });

  it("prose before AND after one fenced block still extracts", () => {
    const raw = 'Here is the plan.\n```json\n{"calls": []}\n```\nLet me know if you need changes.';
    expect(extractPlanJson(raw)).toEqual({ calls: [] });
  });

  it("a ``` sequence inside a string value is inert (bare JSON and fenced)", () => {
    const call = { method: "voidInvoice", invoiceId: 2, reason: "x```y" };
    expect(extractPlanJson(JSON.stringify({ calls: [call] }))).toEqual({ calls: [call] });
    expect(extractPlanJson("```json\n" + JSON.stringify({ calls: [call] }) + "\n```")).toEqual({ calls: [call] });
  });

  it("a newline-``` sequence inside a string value truncates the fence body -> SyntaxError", () => {
    // The regex terminates the body at the first \n```, leaving unparseable
    // JSON; documented "unparseable body is malformed" behavior, but the error
    // is a raw SyntaxError, not the fence-count message.
    const raw = '```json\n{"reason": "line1\n```\nline2"}\n```';
    expect(() => extractPlanJson(raw)).toThrow(SyntaxError);
  });

  it("nested fence blocks: the outer fence swallows the inner one -> SyntaxError", () => {
    // One regex block with an unparseable body; no "expected exactly 1" error.
    expect(() => extractPlanJson('```\n```json\n{"calls": []}\n```\n```')).toThrow(SyntaxError);
  });

  it("duplicate keys: JSON.parse keeps the LAST occurrence, silently", () => {
    // Standard JSON.parse semantics; a model emitting duplicate "calls" keys
    // gets last-wins with no error. Pinned as a note, not a defect.
    const raw = '{"calls": [], "calls": [{"method": "voidInvoice", "invoiceId": 2, "reason": "r"}]}';
    expect(extractPlanJson(raw)).toEqual({ calls: [{ method: "voidInvoice", invoiceId: 2, reason: "r" }] });
  });

  it.each<[string, string, unknown]>([
    ["number", "42", 42],
    ["string", '"a string"', "a string"],
    ["null", "null", null],
    ["boolean", "true", true],
  ])("valid JSON primitive (%s) extracts but fails PlanSchema", (_label, raw, expected) => {
    expect(extractPlanJson(raw)).toEqual(expected);
    expect(PlanSchema.safeParse(extractPlanJson(raw)).success).toBe(false);
  });
});

describe("plan schema (red-team edges)", () => {
  it("ids of 0 or negative integers are schema-valid; the domain API is the rejecting layer", () => {
    expect(PlanSchema.safeParse({ calls: [{ method: "transferTicket", ticketId: 0, toCustomerId: -3 }] }).success).toBe(
      true,
    );
    expect(PlanSchema.safeParse({ calls: [{ method: "voidInvoice", invoiceId: -1, reason: REASON }] }).success).toBe(
      true,
    );
  });

  it("empty-string reasons are schema-valid", () => {
    expect(PlanSchema.safeParse({ calls: [{ method: "voidInvoice", invoiceId: 2, reason: "" }] }).success).toBe(true);
    expect(PlanSchema.safeParse({ calls: [{ method: "deactivateCustomer", customerId: 2, reason: "" }] }).success).toBe(
      true,
    );
  });

  it("extra unknown keys are STRIPPED, not rejected (call level and plan level)", () => {
    const plan = PlanSchema.parse({
      calls: [{ method: "voidInvoice", invoiceId: 2, reason: REASON, commentary: "haha" }],
      thoughts: "stripped too",
    });
    expect(plan).toEqual({ calls: [{ method: "voidInvoice", invoiceId: 2, reason: REASON }] });
  });

  it("details accepts nested objects, arrays, and unicode", () => {
    const details = { meta: { tags: ["αβγ", "🚀"], nested: { deep: [true, { deeper: "✓" }] } } };
    const parsed = PlanSchema.parse({
      calls: [{ method: "writeAuditEvent", action: "a", entityType: "customer", entityId: 2, details }],
    });
    expect(parsed.calls[0]).toMatchObject({ details });
  });
});

describe("episode classification (red-team edges)", () => {
  const cf = getCase("original-incident");

  it("schema-valid but domain-meaningless id 0 is caught by the domain API, not the schema", async () => {
    const episode = await runAgentEpisode(
      cf,
      scriptedProvider(JSON.stringify({ calls: [{ method: "voidInvoice", invoiceId: 0, reason: REASON }] })),
      config,
    );
    expect(episode.outcome).toBe("invalid-action");
    expect(episode.abortedAtCall).toMatchObject({ index: 0, method: "voidInvoice" });
    expect(episode.abortedAtCall?.error).toContain("invoice 0 does not exist");
  });

  it("abort at call index 0: invalid-action with executedCalls 0", async () => {
    const episode = await runAgentEpisode(
      cf,
      scriptedProvider(JSON.stringify({ calls: [{ method: "transferTicket", ticketId: 1, toCustomerId: 999 }] })),
      config,
    );
    expect(episode.outcome).toBe("invalid-action");
    expect(episode.executedCalls).toBe(0);
    expect(episode.executionLog).toHaveLength(1);
    expect(episode.abortedAtCall?.index).toBe(0);
  });

  it("an empty calls array executes nothing and classifies as business-violation (untouched state fails)", async () => {
    const episode = await runAgentEpisode(cf, scriptedProvider('{"calls": []}'), config);
    expect(episode.plan?.calls).toEqual([]);
    expect(episode.outcome).toBe("business-violation");
    expect(episode.executedCalls).toBe(0);
    expect(episode.abortedAtCall).toBeNull();
    expect(episode.violations.map((v) => v.invariant)).toContain("single-active-canonical");
  });

  it("semantically absurd self-transfer (ticket to its current owner) executes cleanly -> business-violation", async () => {
    // No no-op guard in the domain API; the verifier is the backstop.
    const episode = await runAgentEpisode(
      cf,
      scriptedProvider(JSON.stringify({ calls: [{ method: "transferTicket", ticketId: 1, toCustomerId: 2 }] })),
      config,
    );
    expect(episode.executionLog[0]).toMatchObject({ ok: true });
    expect(episode.outcome).toBe("business-violation");
  });

  it("voiding the same invoice twice: the second void aborts as invalid-action", async () => {
    const plan = JSON.stringify({
      calls: [
        { method: "voidInvoice", invoiceId: 2, reason: REASON },
        { method: "voidInvoice", invoiceId: 2, reason: REASON },
      ],
    });
    const episode = await runAgentEpisode(cf, scriptedProvider(plan), config);
    expect(episode.outcome).toBe("invalid-action");
    expect(episode.executedCalls).toBe(1);
    expect(episode.abortedAtCall).toMatchObject({ index: 1, method: "voidInvoice" });
    expect(episode.abortedAtCall?.error).toContain("already void");
  });

  it("writeAuditEvent with a wrong action string executes cleanly; the verifier flags it (business-violation)", async () => {
    const plan = JSON.parse(CORRECT_PLAN) as { calls: Record<string, unknown>[] };
    plan.calls[3].action = "customer.dedup.merged"; // typo'd action, schema-valid string
    const episode = await runAgentEpisode(cf, scriptedProvider(JSON.stringify(plan)), config);
    expect(episode.executionLog).toHaveLength(4);
    expect(episode.executionLog.every((entry) => entry.ok)).toBe(true);
    expect(episode.outcome).toBe("business-violation"); // not invalid-action
    expect(episode.violations.map((v) => v.invariant)).toContain("accurate-audit-event");
  });

  it("PlanSchema-invalid output while the untouched state has violations still classifies malformed-output", async () => {
    const episode = await runAgentEpisode(
      cf,
      scriptedProvider('{"calls": [{"method": "deleteCustomer", "customerId": 2}]}'),
      config,
    );
    expect(episode.violations.length).toBeGreaterThan(0); // untouched state fails the verifier
    expect(episode.outcome).toBe("malformed-output"); // precedence holds end to end
    expect(episode.planError).not.toBeNull();
  });

  it("a provider.complete throwing a plain Error (not ProviderCallError) classifies as infrastructure", async () => {
    const buggy: ProviderDriver = {
      name: "buggy",
      complete: async () => {
        throw new Error("driver bug: cannot read properties of undefined");
      },
    };
    const episode = await runAgentEpisode(cf, buggy, config);
    expect(episode.outcome).toBe("infrastructure");
    expect(episode.rawResponse).toBeNull();
    expect(episode.planError).toBeNull();
    // Note: the driver wraps the throw as ProviderCallError kind "unknown";
    // classifyEpisode does not discriminate kinds, so a driver bug is retried
    // and excluded exactly like a network fault. Pinned as acceptable per the
    // taxonomy, but it can mask harness bugs.
  });

  it("empty call-level reasons are invisible: never checked by API or verifier (pass)", async () => {
    const plan = JSON.parse(CORRECT_PLAN) as { calls: Record<string, unknown>[] };
    plan.calls[0].reason = "";
    plan.calls[2].reason = "";
    const episode = await runAgentEpisode(cf, scriptedProvider(JSON.stringify(plan)), config);
    expect(episode.outcome).toBe("pass");
    expect(episode.violations).toEqual([]);
    // Note: the call-level reason has no column and no check; only the audit
    // event's details.reason is verified. Acceptable per the domain API's
    // documented contract.
  });

  it("an empty details.reason is caught by the verifier -> business-violation", async () => {
    const plan = JSON.parse(CORRECT_PLAN) as { calls: { details?: Record<string, unknown> }[] };
    plan.calls[3].details = { ...plan.calls[3].details, reason: "" };
    const episode = await runAgentEpisode(cf, scriptedProvider(JSON.stringify(plan)), config);
    expect(episode.outcome).toBe("business-violation");
    expect(episode.violations.map((v) => v.invariant)).toContain("accurate-audit-event");
  });

  it("nested objects, arrays, and unicode in details round-trip to a pass", async () => {
    const plan = JSON.parse(CORRECT_PLAN) as { calls: { details?: Record<string, unknown> }[] };
    plan.calls[3].details = {
      ...plan.calls[3].details,
      extra: { tags: ["αβγ", "🚀"], nested: { deep: [1, { two: "✓" }] } },
    };
    const episode = await runAgentEpisode(cf, scriptedProvider(JSON.stringify(plan)), config);
    expect(episode.outcome).toBe("pass");
  });

  it("prose + one fenced block + prose still executes a correct plan to a pass", async () => {
    const raw = "Here is the plan you asked for:\n```json\n" + CORRECT_PLAN + "\n```\nLet me know if you need changes.";
    const episode = await runAgentEpisode(cf, scriptedProvider(raw), config);
    expect(episode.outcome).toBe("pass");
  });

  it("extra unknown keys are stripped before execution and never reach the execution log", async () => {
    const plan = JSON.parse(CORRECT_PLAN) as { calls: Record<string, unknown>[] };
    plan.calls[0].commentary = "the model explaining itself";
    const episode = await runAgentEpisode(cf, scriptedProvider(JSON.stringify(plan)), config);
    expect(episode.outcome).toBe("pass");
    expect(episode.executionLog[0].args).toEqual({ invoiceId: 2, reason: REASON });
  });
});

describe("runner (red-team edges)", () => {
  const cf = getCase("original-incident");

  it("k=1 minimum sanity", async () => {
    const summary = await runAgentEvaluation(cf, 1, { provider: scriptedProvider(CORRECT_PLAN), config });
    expect(summary.k).toBe(1);
    expect(summary.passRate).toBe(1);
    expect(summary.counts.pass).toBe(1);
    expect(summary.episodes).toHaveLength(1);
  });

  it("infrastructure-then-success: the retry is recorded via infraRetries and transcript attempts/infraErrors; counts stay final", async () => {
    // PLAN-agent: infrastructure is "retried once, then excluded and noted",
    // and the audit substance rules want infrastructure episodes "counted and
    // described". A recovered retry is now "noted" WITHOUT touching
    // final-outcome counts: summary.infraRetries counts the episode, and the
    // transcript carries attempts: 2 plus the first attempt's kind/message.
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-retry-"));
    try {
      let calls = 0;
      const flaky: ProviderDriver = {
        name: "flaky",
        complete: async () => {
          calls += 1;
          if (calls === 1) throw new ProviderCallError("flaky", "rate-limit", "HTTP 429");
          return { text: CORRECT_PLAN };
        },
      };
      const summary = await runAgentEvaluation(cf, 1, { provider: flaky, config, episodesDir });
      expect(calls).toBe(2);
      expect(summary.infraRetries).toBe(1);
      expect(summary.counts.infrastructure).toBe(0); // counts stay final-outcome-only
      expect(summary.excluded).toBe(0);
      expect(summary.counts.pass).toBe(1);
      expect(summary.passRate).toBe(1);
      expect(summary.episodes).toHaveLength(1); // the episodes array holds the final attempt only
      expect(summary.episodes[0].providerError).toBeNull();
      const dir = join(episodesDir, cf.trace.case_id);
      expect(readdirSync(dir)).toEqual(["episode-0.json"]);
      const transcript = TranscriptSchema.parse(JSON.parse(readFileSync(join(dir, "episode-0.json"), "utf8")));
      expect(transcript.outcome).toBe("pass");
      expect(transcript.attempts).toBe(2);
      expect(transcript.infraErrors).toEqual([{ attempt: 1, kind: "rate-limit", message: "HTTP 429" }]);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("double-infrastructure is noted via counts, excluded, and an on-disk transcript", async () => {
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-down-"));
    try {
      const down: ProviderDriver = {
        name: "down",
        complete: async () => {
          throw new ProviderCallError("down", "network", "connection refused");
        },
      };
      const summary = await runAgentEvaluation(cf, 1, { provider: down, config, episodesDir });
      expect(summary.counts.infrastructure).toBe(1);
      expect(summary.excluded).toBe(1);
      expect(summary.passRate).toBeNull();
      const raw = readFileSync(join(episodesDir, cf.trace.case_id, "episode-0.json"), "utf8");
      const transcript = JSON.parse(raw) as Record<string, unknown>;
      expect(transcript.outcome).toBe("infrastructure");
      expect(transcript.rawResponse).toBeNull();
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("an excluded infrastructure episode records both attempts' kind and message (transcript and audit)", async () => {
    // The "noted" half of the retry rule on the double-failure path: the
    // transcript keeps one infraErrors entry per infrastructure ATTEMPT, the
    // EpisodeResult keeps the final attempt's error, and the audit flattens
    // every entry with its file path — so excluded episodes can be described
    // (429 vs timeout vs driver bug) from on-disk evidence.
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-down-detail-"));
    try {
      let calls = 0;
      const down: ProviderDriver = {
        name: "down",
        complete: async () => {
          calls += 1;
          throw new ProviderCallError("down", calls === 1 ? "network" : "timeout", `attempt-${calls} failed`);
        },
      };
      const summary = await runAgentEvaluation(cf, 1, { provider: down, config, episodesDir });
      expect(summary.counts.infrastructure).toBe(1);
      expect(summary.excluded).toBe(1);
      expect(summary.infraRetries).toBe(0); // a double-failure is excluded, not a recovered retry
      expect(summary.episodes[0].providerError).toEqual({ kind: "timeout", message: "attempt-2 failed" });
      const transcript = TranscriptSchema.parse(
        JSON.parse(readFileSync(join(episodesDir, cf.trace.case_id, "episode-0.json"), "utf8")),
      );
      expect(transcript.outcome).toBe("infrastructure");
      expect(transcript.attempts).toBe(2);
      expect(transcript.infraErrors).toEqual([
        { attempt: 1, kind: "network", message: "attempt-1 failed" },
        { attempt: 2, kind: "timeout", message: "attempt-2 failed" },
      ]);
      const data = aggregateEpisodes(episodesDir);
      expect(data.totals.infraErrors).toHaveLength(2);
      expect(data.totals.infraErrors.map((entry) => entry.kind)).toEqual(["network", "timeout"]);
      for (const entry of data.totals.infraErrors) expect(entry.file).toContain("episode-0.json");
      expect(data.cases[0].infraErrors).toHaveLength(2);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("rerunning the same k overwrites same-index transcripts (deterministic filenames, acceptable)", async () => {
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-overwrite-"));
    try {
      await runAgentEvaluation(cf, 1, { provider: scriptedProvider(CORRECT_PLAN), config, episodesDir });
      await runAgentEvaluation(cf, 1, { provider: scriptedProvider("no json here"), config, episodesDir });
      const dir = join(episodesDir, cf.trace.case_id);
      expect(readdirSync(dir)).toEqual(["episode-0.json"]);
      const transcript = JSON.parse(readFileSync(join(dir, "episode-0.json"), "utf8")) as { outcome: string };
      expect(transcript.outcome).toBe("malformed-output"); // second run's content
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("a smaller-k rerun leaves no stale transcripts: the runner cleans the case dir before each run", async () => {
    // Fix for the stale-tail finding: runAgentEvaluation deletes
    // episode-*.json in the case dir before writing, so a mixed-k rerun
    // cannot leak old transcripts into the audit aggregation.
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-stale-"));
    try {
      await runAgentEvaluation(cf, 2, { provider: scriptedProvider(CORRECT_PLAN), config, episodesDir });
      await runAgentEvaluation(cf, 1, { provider: scriptedProvider(CORRECT_PLAN), config, episodesDir });
      expect(readdirSync(join(episodesDir, cf.trace.case_id))).toEqual(["episode-0.json"]);
      expect(aggregateEpisodes(episodesDir).totals.k).toBe(1);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });
});

describe("provider selection (red-team edges)", () => {
  it.each<[ProviderName, string]>([
    ["anthropic", "claude-sonnet-4-5-20250929"],
    ["openai", "gpt-4.1"],
    ["openrouter", "anthropic/claude-sonnet-4.5"],
    ["ollama", "llama3.1:8b"],
    ["cursor", "composer-2.5"],
  ])("PROVIDER=%s overrides the file's provider and resolves its model", (name, model) => {
    vi.stubEnv("PROVIDER", name);
    const resolved = loadAgentConfig();
    expect(resolved.provider).toBe(name);
    expect(resolved.model).toBe(model);
    expect(resolved.temperature).toBe(0);
    expect(resolved.maxTokens).toBe(8192);
  });

  it("PROVIDER is case-sensitive and an empty string does not fall back to the file", () => {
    vi.stubEnv("PROVIDER", "OpenAI");
    expect(() => loadAgentConfig()).toThrow('unknown provider "OpenAI"');
    vi.stubEnv("PROVIDER", "");
    expect(() => loadAgentConfig()).toThrow('unknown provider ""');
  });

  it("a config whose provider has no entry under \"providers\" fails with a clear error", () => {
    vi.stubEnv("PROVIDER", undefined);
    const dir = mkdtempSync(join(tmpdir(), "agent-redteam-config-"));
    try {
      const path = join(dir, "agent.config.json");
      writeFileSync(
        path,
        JSON.stringify({
          provider: "ollama",
          providers: { anthropic: { model: "x" } },
          temperature: 0,
          max_tokens: 100,
        }),
      );
      expect(() => loadAgentConfig(path)).toThrow(/provider "ollama" has no entry under "providers"/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("a malformed JSON config fails with a raw SyntaxError (no file-path context)", () => {
    // Pin of actual behavior. Error clarity is a note: the message names no
    // path, so an operator editing agent.config.json by hand gets a bare
    // SyntaxError. Acceptable, could be friendlier.
    vi.stubEnv("PROVIDER", undefined);
    const dir = mkdtempSync(join(tmpdir(), "agent-redteam-config-bad-"));
    try {
      const path = join(dir, "agent.config.json");
      writeFileSync(path, "{ definitely not json");
      expect(() => loadAgentConfig(path)).toThrow(SyntaxError);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it.each<[ProviderName, string]>([
    ["anthropic", "ANTHROPIC_API_KEY"],
    ["openai", "OPENAI_API_KEY"],
    ["openrouter", "OPENROUTER_API_KEY"],
    ["cursor", "CURSOR_API_KEY"],
  ])("createProvider(%s) with a missing key throws naming %s and never falls through", async (name, envVar) => {
    // All keys deleted: if selection fell through to another provider, the
    // error would name that provider's env var (or succeed) instead.
    vi.stubEnv("ANTHROPIC_API_KEY", undefined);
    vi.stubEnv("OPENAI_API_KEY", undefined);
    vi.stubEnv("OPENROUTER_API_KEY", undefined);
    vi.stubEnv("CURSOR_API_KEY", undefined);
    await expect(createProvider({ ...config, provider: name })).rejects.toThrow(
      `${name} provider requires ${envVar} in the environment`,
    );
  });

  it("OLLAMA_HOST trailing slashes are stripped; the default base URL is localhost:11434", async () => {
    const urls: string[] = [];
    const fetchImpl = (async (url: string) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => ({ message: { content: "ok" } }) };
    }) as unknown as typeof fetch;

    vi.stubEnv("OLLAMA_HOST", "http://example.com:11434///");
    await createOllamaDriver(config, { fetch: fetchImpl }).complete(REQUEST);
    expect(urls[0]).toBe("http://example.com:11434/api/chat");

    vi.stubEnv("OLLAMA_HOST", undefined);
    await createOllamaDriver(config, { fetch: fetchImpl }).complete(REQUEST);
    expect(urls[1]).toBe("http://localhost:11434/api/chat");
  });
});

describe("audit-report (red-team edges)", () => {
  const cf = getCase("original-incident");

  const runInto = async (
    episodesDir: string,
    k: number,
    overrides: { provider?: ProviderDriver; model?: string } = {},
  ) =>
    runAgentEvaluation(cf, k, {
      provider: overrides.provider ?? scriptedProvider(CORRECT_PLAN),
      config: { ...config, model: overrides.model ?? config.model },
      episodesDir,
    });

  it("transcripts missing usage: token sums stay 0 and costUsd is null for an unpriced model", async () => {
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-audit-"));
    try {
      await runInto(episodesDir, 1); // scripted provider returns no usage; test-model has no price
      const data = aggregateEpisodes(episodesDir);
      expect(data.cases[0]).toMatchObject({ k: 1, inputTokens: 0, outputTokens: 0, costUsd: null });
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("transcripts missing usage with a PRICED model: costUsd is a defined 0, not null", async () => {
    // costUsd distinguishes "no priced episodes" (null) from "priced episodes
    // with zero recorded tokens" (0) — pinned.
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-audit-priced-"));
    try {
      await runInto(episodesDir, 1, { model: "gpt-4.1" });
      const data = aggregateEpisodes(episodesDir);
      expect(data.cases[0]).toMatchObject({ k: 1, inputTokens: 0, outputTokens: 0, costUsd: 0 });
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("usage and a priced model aggregate to an exact cost", async () => {
    const provider: ProviderDriver = {
      name: "metered",
      complete: async () => ({ text: CORRECT_PLAN, usage: { inputTokens: 1000, outputTokens: 500 } }),
    };
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-audit-cost-"));
    try {
      await runInto(episodesDir, 1, { provider, model: "gpt-4.1" }); // $2/M in, $8/M out
      const data = aggregateEpisodes(episodesDir);
      expect(data.cases[0]).toMatchObject({ inputTokens: 1000, outputTokens: 500 });
      expect(data.cases[0].costUsd).toBeCloseTo(0.006, 10);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("a malformed transcript file fails LOUD (throws), and that is correct for an audit tool", async () => {
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-audit-bad-"));
    try {
      await runInto(episodesDir, 1);
      writeFileSync(join(episodesDir, cf.trace.case_id, "episode-7.json"), '{"case_id": 123}');
      // Silently skipping would corrupt audit distributions; a hard failure is
      // the right behavior. Pinned as correct.
      expect(() => aggregateEpisodes(episodesDir)).toThrow(z.ZodError);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("non-episode files in a case dir, and stray files at the episodes root, are ignored", async () => {
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-audit-junk-"));
    try {
      await runInto(episodesDir, 1);
      const caseDir = join(episodesDir, cf.trace.case_id);
      for (const junk of ["notes.txt", "episode-0.json.bak", "episode-x.json", "episode-1.JSON"]) {
        writeFileSync(join(caseDir, junk), "junk");
      }
      writeFileSync(join(episodesDir, "stray.json"), "junk"); // not a case directory
      const data = aggregateEpisodes(episodesDir);
      expect(data.totals.k).toBe(1);
      expect(data.episodes).toHaveLength(1);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });

  it("infraRetries and infraErrors aggregate for a mixed run; the audit counts retries more broadly than the runner", async () => {
    // Naming difference, pinned for the AUDIT author: the runner's
    // infraRetries counts RECOVERED episodes only (first attempt
    // infrastructure, final outcome not); the audit's counts every transcript
    // with attempts > 1, which also includes double-failures. Same run, two
    // numbers: runner 1, audit 2.
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-redteam-audit-infra-"));
    try {
      let calls = 0;
      const mixed: ProviderDriver = {
        name: "mixed",
        complete: async () => {
          calls += 1;
          if (calls === 1) throw new ProviderCallError("mixed", "rate-limit", "HTTP 429");
          if (calls === 3) throw new ProviderCallError("mixed", "timeout", "attempt-1 timeout");
          if (calls === 4) throw new ProviderCallError("mixed", "timeout", "attempt-2 timeout");
          return { text: CORRECT_PLAN };
        },
      };
      const summary = await runInto(episodesDir, 3, { provider: mixed });
      expect(calls).toBe(5); // episode 0 retried once, episode 1 retried once, episode 2 clean
      expect(summary.infraRetries).toBe(1); // recovered only
      expect(summary.counts).toMatchObject({ pass: 2, infrastructure: 1 });
      expect(summary.excluded).toBe(1);
      expect(summary.passRate).toBe(1);
      const data = aggregateEpisodes(episodesDir);
      expect(data.totals.k).toBe(3);
      expect(data.totals.infraRetries).toBe(2); // the recovered retry AND the double-failure
      expect(data.totals.infraErrors.map((entry) => entry.kind)).toEqual(["rate-limit", "timeout", "timeout"]);
      expect(data.totals.infraErrors[0].file).toContain("episode-0.json");
      expect(data.totals.infraErrors[1].file).toContain("episode-1.json");
      expect(data.totals.infraErrors[2].file).toContain("episode-1.json");
      expect(data.cases[0]).toMatchObject({ infraRetries: 2 });
      expect(data.cases[0].infraErrors).toHaveLength(3);
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });
});
