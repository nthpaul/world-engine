import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type Anthropic from "@anthropic-ai/sdk";
import { APIError as AnthropicApiError } from "@anthropic-ai/sdk";
import type OpenAI from "openai";
import { APIError as OpenAiApiError } from "openai";
import { loadCases, type CaseFile } from "../src/cases";
import { defineTask } from "../src/task";
import { runAsyncEvaluation } from "../src/report";
import type { Violation } from "../src/schemas";
import { loadAgentConfig, PROVIDER_NAMES, type ResolvedAgentConfig } from "../src/agent/config";
import { PlanSchema } from "../src/agent/plan-schema";
import { buildPrompt, type AgentStateView } from "../src/agent/prompt";
import { extractPlanJson, runAgentEpisode } from "../src/agent/driver";
import { classifyEpisode } from "../src/agent/classify";
import { runAgentEvaluation, TranscriptSchema } from "../src/agent/runner";
import { createAnthropicDriver } from "../src/agent/providers/anthropic";
import { createOpenAiDriver } from "../src/agent/providers/openai";
import { createOpenRouterDriver } from "../src/agent/providers/openrouter";
import { createOllamaDriver } from "../src/agent/providers/ollama";
import { createCursorDriver, type CursorPromptFn } from "../src/agent/providers/cursor";
import { createProvider } from "../src/agent/providers";
import { ProviderCallError, type CompletionRequest, type ProviderDriver } from "../src/agent/providers/types";

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

// A fully correct merge of the original incident's pair (customer 2 into
// canonical customer 1) as a single-shot plan, audit event included.
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

describe("plan schema", () => {
  const validCall = { method: "transferTicket", ticketId: 1, toCustomerId: 2 };

  it("a valid plan with one call of each method parses", () => {
    const plan = PlanSchema.parse({
      calls: [
        validCall,
        { method: "transferInvoice", invoiceId: 3, toCustomerId: 1 },
        { method: "voidInvoice", invoiceId: 2, reason: REASON },
        { method: "deactivateCustomer", customerId: 2, reason: REASON },
        {
          method: "writeAuditEvent",
          action: "customer.dedup.merge",
          entityType: "customer",
          entityId: 2,
          details: { reason: REASON },
        },
      ],
    });
    expect(plan.calls).toHaveLength(5);
  });

  it.each<[string, unknown]>([
    ["transferTicket missing toCustomerId", { method: "transferTicket", ticketId: 1 }],
    ["transferTicket with a string ticketId", { method: "transferTicket", ticketId: "1", toCustomerId: 2 }],
    ["transferInvoice missing invoiceId", { method: "transferInvoice", toCustomerId: 1 }],
    ["transferInvoice with a string toCustomerId", { method: "transferInvoice", invoiceId: 3, toCustomerId: "1" }],
    ["voidInvoice missing reason", { method: "voidInvoice", invoiceId: 2 }],
    ["deactivateCustomer missing customerId", { method: "deactivateCustomer", reason: REASON }],
    ["deactivateCustomer missing reason", { method: "deactivateCustomer", customerId: 2 }],
    ["writeAuditEvent missing action", { method: "writeAuditEvent", entityType: "customer", entityId: 2, details: {} }],
    ["writeAuditEvent missing details", { method: "writeAuditEvent", action: "a", entityType: "customer", entityId: 2 }],
  ])("rejects wrong/missing args: %s", (_label, call) => {
    expect(PlanSchema.safeParse({ calls: [call] }).success).toBe(false);
  });

  it("rejects an unknown method", () => {
    const call = { method: "deleteCustomer", customerId: 2 };
    expect(PlanSchema.safeParse({ calls: [call] }).success).toBe(false);
  });

  it("rejects entityType other than \"customer\"", () => {
    const call = { method: "writeAuditEvent", action: "a", entityType: "invoice", entityId: 2, details: {} };
    expect(PlanSchema.safeParse({ calls: [call] }).success).toBe(false);
  });

  it("rejects more than 50 calls; accepts exactly 50", () => {
    const over = Array.from({ length: 51 }, () => validCall);
    expect(PlanSchema.safeParse({ calls: over }).success).toBe(false);
    const atLimit = Array.from({ length: 50 }, () => validCall);
    expect(PlanSchema.safeParse({ calls: atLimit }).success).toBe(true);
  });

  it("rejects non-integer ids", () => {
    const call = { method: "transferTicket", ticketId: 1.5, toCustomerId: 2 };
    expect(PlanSchema.safeParse({ calls: [call] }).success).toBe(false);
  });
});

describe("extractPlanJson", () => {
  it("parses bare JSON", () => {
    expect(extractPlanJson('  {"calls": []}  ')).toEqual({ calls: [] });
  });

  it("parses a single ```json fenced block", () => {
    expect(extractPlanJson('```json\n{"calls": []}\n```')).toEqual({ calls: [] });
  });

  it("parses a single bare fenced block", () => {
    expect(extractPlanJson('```\n{"calls": []}\n```')).toEqual({ calls: [] });
  });

  it("throws on prose-only output", () => {
    expect(() => extractPlanJson("I cannot produce a plan.")).toThrow(/0 fenced code blocks/);
  });

  it("throws on TWO fenced blocks (exactly one allowed)", () => {
    const raw = '```json\n{"calls": []}\n```\nand again\n```json\n{"calls": []}\n```';
    expect(() => extractPlanJson(raw)).toThrow(/2 fenced code blocks/);
  });

  it("valid JSON that is not plan-shaped fails PlanSchema", () => {
    expect(PlanSchema.safeParse(extractPlanJson('{"nope": true}')).success).toBe(false);
  });
});

describe("abort on invalid call", () => {
  it("a domain-rejected call mid-plan aborts the rest of the plan", async () => {
    const plan = JSON.stringify({
      calls: [
        { method: "voidInvoice", invoiceId: 2, reason: REASON },
        { method: "transferTicket", ticketId: 1, toCustomerId: 999 },
        { method: "deactivateCustomer", customerId: 2, reason: REASON },
      ],
    });
    const episode = await runAgentEpisode(getCase("original-incident"), scriptedProvider(plan), config);
    expect(episode.outcome).toBe("invalid-action");
    expect(episode.executedCalls).toBe(1);
    expect(episode.executionLog).toHaveLength(2);
    expect(episode.executionLog[0]).toMatchObject({ index: 0, method: "voidInvoice", ok: true });
    expect(episode.executionLog[1]).toMatchObject({ index: 1, method: "transferTicket", ok: false });
    expect(episode.executionLog[1].error).toContain("customer 999 does not exist");
    expect(episode.abortedAtCall).toMatchObject({ index: 1, method: "transferTicket" });
    // deactivateCustomer(2) never ran: the pair is still two active customers.
    expect(episode.violations.map((v) => v.invariant)).toContain("single-active-canonical");
  });
});

describe("classifyEpisode", () => {
  const providerError = new ProviderCallError("fake", "network", "connection refused");
  const violation: Violation = { invariant: "single-active-canonical", message: "m" };

  it("provider error -> infrastructure", () => {
    expect(classifyEpisode({ providerError, planParsed: true, domainApiRejected: false, violations: [] })).toBe(
      "infrastructure",
    );
  });

  it("unparseable plan -> malformed-output", () => {
    expect(classifyEpisode({ providerError: null, planParsed: false, domainApiRejected: false, violations: [] })).toBe(
      "malformed-output",
    );
  });

  it("domain rejection -> invalid-action", () => {
    expect(classifyEpisode({ providerError: null, planParsed: true, domainApiRejected: true, violations: [] })).toBe(
      "invalid-action",
    );
  });

  it("clean execution with violations -> business-violation", () => {
    expect(
      classifyEpisode({ providerError: null, planParsed: true, domainApiRejected: false, violations: [violation] }),
    ).toBe("business-violation");
  });

  it("clean execution with zero violations -> pass", () => {
    expect(classifyEpisode({ providerError: null, planParsed: true, domainApiRejected: false, violations: [] })).toBe(
      "pass",
    );
  });

  it("precedence: providerError + violations -> infrastructure", () => {
    expect(classifyEpisode({ providerError, planParsed: false, domainApiRejected: true, violations: [violation] })).toBe(
      "infrastructure",
    );
  });

  it("precedence: planParsed false + domainApiRejected true -> malformed-output", () => {
    expect(
      classifyEpisode({ providerError: null, planParsed: false, domainApiRejected: true, violations: [violation] }),
    ).toBe("malformed-output");
  });
});

describe("runAgentEvaluation with a fake driver", () => {
  const cf = getCase("original-incident");

  it("k episodes of a fully-correct plan yield passRate 1 and counts.pass === k", async () => {
    const summary = await runAgentEvaluation(cf, 3, { provider: scriptedProvider(CORRECT_PLAN), config });
    expect(summary.k).toBe(3);
    expect(summary.passRate).toBe(1);
    expect(summary.counts.pass).toBe(3);
    expect(summary.excluded).toBe(0);
    expect(summary.episodes.map((e) => e.outcome)).toEqual(["pass", "pass", "pass"]);
  });

  it("a ProviderCallError once then success exercises retry-once; the final outcome is counted", async () => {
    let calls = 0;
    const flaky: ProviderDriver = {
      name: "flaky",
      complete: async () => {
        calls += 1;
        if (calls === 1) throw new ProviderCallError("flaky", "rate-limit", "HTTP 429");
        return { text: CORRECT_PLAN };
      },
    };
    const summary = await runAgentEvaluation(cf, 1, { provider: flaky, config });
    expect(calls).toBe(2);
    expect(summary.counts.infrastructure).toBe(0);
    expect(summary.counts.pass).toBe(1);
    expect(summary.passRate).toBe(1);
  });

  it("a provider that always throws ProviderCallError yields excluded === k and passRate null", async () => {
    let calls = 0;
    const down: ProviderDriver = {
      name: "down",
      complete: async () => {
        calls += 1;
        throw new ProviderCallError("down", "network", "connection refused");
      },
    };
    const summary = await runAgentEvaluation(cf, 2, { provider: down, config });
    expect(calls).toBe(4); // one retry per episode
    expect(summary.counts.infrastructure).toBe(2);
    expect(summary.excluded).toBe(2);
    expect(summary.passRate).toBeNull();
    expect(summary.episodes.every((e) => e.rawResponse === null)).toBe(true);
  });

  it("fresh reconstruction per episode: mutations do not leak into the next episode", async () => {
    const summary = await runAgentEvaluation(cf, 2, { provider: scriptedProvider(CORRECT_PLAN), config });
    expect(summary.episodes.map((e) => e.outcome)).toEqual(["pass", "pass"]);
    expect(summary.episodes[1].report.initial_digest).toBe(summary.episodes[0].report.initial_digest);
    expect(summary.episodes[1].report.final_digest).toBe(summary.episodes[0].report.final_digest);
  });

  it("writes schema-valid transcripts as episode-<index>.json, free of API key material", async () => {
    const episodesDir = mkdtempSync(join(tmpdir(), "agent-runner-"));
    const keys: [string, string][] = [
      ["ANTHROPIC_API_KEY", "sk-ant-test-dummy"],
      ["OPENAI_API_KEY", "sk-openai-test-dummy"],
      ["OPENROUTER_API_KEY", "sk-or-test-dummy"],
      ["CURSOR_API_KEY", "cursor_test_dummy"],
    ];
    for (const [name, value] of keys) vi.stubEnv(name, value);
    try {
      const summary = await runAgentEvaluation(cf, 2, {
        provider: scriptedProvider(CORRECT_PLAN),
        config,
        episodesDir,
      });
      expect(summary.counts.pass).toBe(2);
      const dir = join(episodesDir, cf.trace.case_id);
      const files = readdirSync(dir).sort();
      expect(files).toEqual(["episode-0.json", "episode-1.json"]);
      for (const [index, file] of files.entries()) {
        const raw = readFileSync(join(dir, file), "utf8");
        const transcript = TranscriptSchema.parse(JSON.parse(raw));
        expect(transcript.case_id).toBe(cf.trace.case_id);
        expect(transcript.index).toBe(index);
        expect(transcript.outcome).toBe("pass");
        expect(transcript.prompt).toContain("normalized email");
        expect(transcript.rawResponse).toBe(CORRECT_PLAN);
        expect(transcript.plan?.calls).toHaveLength(4);
        expect(transcript.executionLog).toHaveLength(4);
        expect(transcript.violations).toEqual([]);
        expect(transcript.model).toBe(config.model);
        expect(transcript.wallMs).toBeGreaterThanOrEqual(0);
        for (const [, value] of keys) expect(raw).not.toContain(value);
      }
    } finally {
      rmSync(episodesDir, { recursive: true, force: true });
    }
  });
});

describe("provider drivers (mocked transports, no network)", () => {
  const anthropicClient = (create: () => Promise<unknown>) =>
    ({ messages: { create } }) as unknown as Anthropic;
  const openAiClient = (create: () => Promise<unknown>) =>
    ({ chat: { completions: { create } } }) as unknown as OpenAI;

  it("anthropic: maps text blocks and usage", async () => {
    const client = anthropicClient(async () => ({
      content: [
        { type: "text", text: "hello " },
        { type: "thinking", thinking: "..." },
        { type: "text", text: "world" },
      ],
      usage: { input_tokens: 12, output_tokens: 7 },
    }));
    const res = await createAnthropicDriver(config, { client }).complete(REQUEST);
    expect(res.text).toBe("hello world");
    expect(res.usage).toEqual({ inputTokens: 12, outputTokens: 7 });
  });

  it("anthropic: a 429 SDK error maps to ProviderCallError kind rate-limit", async () => {
    const client = anthropicClient(async () => {
      throw new AnthropicApiError(429, undefined, "slow down", undefined);
    });
    const err = await createAnthropicDriver(config, { client })
      .complete(REQUEST)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProviderCallError);
    expect((err as ProviderCallError).kind).toBe("rate-limit");
    expect((err as ProviderCallError).provider).toBe("anthropic");
  });

  it("openai: maps choices text and usage", async () => {
    const client = openAiClient(async () => ({
      choices: [{ message: { content: "hi from openai" } }],
      usage: { prompt_tokens: 9, completion_tokens: 4 },
    }));
    const res = await createOpenAiDriver(config, { client }).complete(REQUEST);
    expect(res.text).toBe("hi from openai");
    expect(res.usage).toEqual({ inputTokens: 9, outputTokens: 4 });
  });

  it("openai: a 429 SDK error maps to ProviderCallError kind rate-limit", async () => {
    const client = openAiClient(async () => {
      throw new OpenAiApiError(429, undefined, "slow down", undefined);
    });
    const err = await createOpenAiDriver(config, { client })
      .complete(REQUEST)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProviderCallError);
    expect((err as ProviderCallError).kind).toBe("rate-limit");
    expect((err as ProviderCallError).provider).toBe("openai");
  });

  it("openrouter: same openai mapping under the openrouter name", async () => {
    const client = openAiClient(async () => ({
      choices: [{ message: { content: "hi from openrouter" } }],
      usage: { prompt_tokens: 3, completion_tokens: 1 },
    }));
    const driver = createOpenRouterDriver(config, { client });
    expect(driver.name).toBe("openrouter");
    const res = await driver.complete(REQUEST);
    expect(res.text).toBe("hi from openrouter");
    expect(res.usage).toEqual({ inputTokens: 3, outputTokens: 1 });
  });

  it("ollama: maps /api/chat content and eval counts to usage", async () => {
    const fetchImpl = (async () => ({
      ok: true,
      status: 200,
      json: async () => ({ message: { content: "hi from ollama" }, prompt_eval_count: 5, eval_count: 2 }),
    })) as unknown as typeof fetch;
    const res = await createOllamaDriver(config, { fetch: fetchImpl }).complete(REQUEST);
    expect(res.text).toBe("hi from ollama");
    expect(res.usage).toEqual({ inputTokens: 5, outputTokens: 2 });
  });

  it("ollama: a thrown TypeError maps to kind network", async () => {
    const fetchImpl = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const err = await createOllamaDriver(config, { fetch: fetchImpl })
      .complete(REQUEST)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProviderCallError);
    expect((err as ProviderCallError).kind).toBe("network");
  });

  it("ollama: an HTTP 500 response maps to a ProviderCallError", async () => {
    const fetchImpl = (async () => ({ ok: false, status: 500 })) as unknown as typeof fetch;
    const err = await createOllamaDriver(config, { fetch: fetchImpl })
      .complete(REQUEST)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProviderCallError);
    expect((err as ProviderCallError).message).toContain("HTTP 500");
  });

  it("cursor: a finished run maps to text with undefined usage", async () => {
    const prompt: CursorPromptFn = async () => ({ id: "run-1", status: "finished", result: "hi from cursor" });
    const res = await createCursorDriver(config, { prompt }).complete(REQUEST);
    expect(res.text).toBe("hi from cursor");
    expect(res.usage).toBeUndefined();
  });

  it("cursor: an error-status run maps to a ProviderCallError", async () => {
    const prompt: CursorPromptFn = async () => ({ id: "run-2", status: "error", error: { message: "boom" } });
    const err = await createCursorDriver(config, { prompt })
      .complete(REQUEST)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProviderCallError);
    expect((err as ProviderCallError).message).toContain("boom");
  });
});

describe("provider factories without a key and without injection", () => {
  const factories: [string, string, () => ProviderDriver][] = [
    ["anthropic", "ANTHROPIC_API_KEY", () => createAnthropicDriver(config)],
    ["openai", "OPENAI_API_KEY", () => createOpenAiDriver(config)],
    ["openrouter", "OPENROUTER_API_KEY", () => createOpenRouterDriver(config)],
    ["cursor", "CURSOR_API_KEY", () => createCursorDriver(config)],
  ];

  it.each(factories)("%s throws naming %s", (provider, envVar, make) => {
    vi.stubEnv(envVar, undefined);
    expect(make).toThrow(`${provider} provider requires ${envVar} in the environment`);
  });
});

describe("createProvider", () => {
  it("resolves ollama with no key needed (lazy import; complete() never called)", async () => {
    const driver = await createProvider({ ...config, provider: "ollama" });
    expect(driver.name).toBe("ollama");
  });

  it.each([...PROVIDER_NAMES])("resolves %s to a driver with the matching name", async (name) => {
    vi.stubEnv("ANTHROPIC_API_KEY", "test-key");
    vi.stubEnv("OPENAI_API_KEY", "test-key");
    vi.stubEnv("OPENROUTER_API_KEY", "test-key");
    vi.stubEnv("CURSOR_API_KEY", "test-key");
    const driver = await createProvider({ ...config, provider: name });
    expect(driver.name).toBe(name);
  });

  it("loadAgentConfig rejects an unknown provider, listing the five valid names", () => {
    vi.stubEnv("PROVIDER", "bogus");
    expect(() => loadAgentConfig()).toThrow(
      'unknown provider "bogus"; valid providers: anthropic, openai, openrouter, ollama, cursor',
    );
  });
});

describe("runAsyncEvaluation", () => {
  it("an async intervention performing the correct merge passes with zero violations", async () => {
    const report = await runAsyncEvaluation(getCase("original-incident"), "async-correct", async (api) => {
      await Promise.resolve();
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 1);
      api.deactivateCustomer(2, REASON);
      api.writeAuditEvent({
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
      });
    });
    expect(report.passed, JSON.stringify(report.violations)).toBe(true);
    expect(report.violations).toEqual([]);
  });

  it("an async intervention that throws mid-way fails with an intervention-completed violation", async () => {
    const report = await runAsyncEvaluation(getCase("original-incident"), "async-throws", async (api) => {
      api.voidInvoice(2, REASON);
      throw new Error("boom mid-merge");
    });
    expect(report.passed).toBe(false);
    const thrown = report.violations.find((v) => v.invariant === "intervention-completed");
    expect(thrown?.message).toContain("boom mid-merge");
  });
});

describe("buildPrompt (contract without answer leakage)", () => {
  const cf = getCase("original-incident");
  const state: AgentStateView = {
    customers: cf.trace.seed.customers.map((customer) => ({
      ...customer,
      tickets: cf.trace.seed.tickets.filter((t) => t.customer_id === customer.id),
      invoices: cf.trace.seed.invoices.filter((i) => i.customer_id === customer.id),
    })),
  };
  const prompt = buildPrompt(defineTask(cf.trace), state);

  it("contains the runbook rules and the current state JSON", () => {
    expect(prompt).toContain("normalized email");
    expect(prompt).toContain("created_at");
    expect(prompt).toContain(JSON.stringify(state, null, 2));
    expect(prompt).toContain("ada@example.com");
  });

  it("does not mention the verifier or its invariants", () => {
    expect(prompt).not.toContain("verifier");
    expect(prompt).not.toContain("invariant");
  });
});
