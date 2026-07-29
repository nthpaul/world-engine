import { z } from "zod";
import type { CaseFile } from "../cases";
import type { DomainApi } from "../domain-api";
import { runAsyncEvaluation } from "../report";
import type { EvaluationReport, Violation } from "../schemas";
import { classifyEpisode, type EpisodeOutcome } from "./classify";
import type { ResolvedAgentConfig } from "./config";
import { PlanSchema, type Plan, type PlanCall } from "./plan-schema";
import { buildPrompt, type AgentStateView } from "./prompt";
import {
  ProviderCallError,
  type CompletionUsage,
  type ProviderDriver,
} from "./providers/types";

export interface CallLogEntry {
  index: number;
  method: PlanCall["method"];
  args: Record<string, unknown>;
  ok: boolean;
  error?: string;
}

export interface EpisodeResult {
  outcome: EpisodeOutcome;
  plan: Plan | null;
  planError: string | null;
  providerError: { kind: string; message: string } | null;
  executionLog: CallLogEntry[];
  executedCalls: number;
  abortedAtCall: { index: number; method: string; error: string } | null;
  violations: Violation[];
  report: EvaluationReport;
  prompt: string;
  rawResponse: string | null;
  model: string;
  usage: CompletionUsage | undefined;
  wallMs: number;
  startedAt: string;
  endedAt: string;
}

// JSON extraction rule: JSON.parse the trimmed response; on failure, extract a
// single fenced (```json / ```) block and parse its body. Zero or multiple
// fences, or an unparseable body, is malformed — no further guessing.
export function extractPlanJson(raw: string): unknown {
  const trimmed = raw.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    // fall through to fenced-block extraction
  }
  const blocks = [...trimmed.matchAll(/```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]*```/g)];
  if (blocks.length !== 1) {
    throw new Error(
      `response is not bare JSON and contains ${blocks.length} fenced code blocks (expected exactly 1)`,
    );
  }
  return JSON.parse(blocks[0][1]);
}

function executeCall(api: DomainApi, call: PlanCall): void {
  switch (call.method) {
    case "transferTicket":
      api.transferTicket(call.ticketId, call.toCustomerId);
      return;
    case "transferInvoice":
      api.transferInvoice(call.invoiceId, call.toCustomerId);
      return;
    case "voidInvoice":
      api.voidInvoice(call.invoiceId, call.reason);
      return;
    case "deactivateCustomer":
      api.deactivateCustomer(call.customerId, call.reason);
      return;
    case "writeAuditEvent":
      api.writeAuditEvent({
        action: call.action,
        entityType: call.entityType,
        entityId: call.entityId,
        details: call.details,
      });
      return;
    default: {
      const exhaustive: never = call;
      throw new Error(`unknown method ${JSON.stringify(exhaustive)}`);
    }
  }
}

export async function runAgentEpisode(
  cf: CaseFile,
  provider: ProviderDriver,
  config: ResolvedAgentConfig,
): Promise<EpisodeResult> {
  const startedAt = new Date();
  let prompt = "";
  let rawResponse: string | null = null;
  let usage: CompletionUsage | undefined;
  // boxed: TS narrowing cannot see assignments made inside the closure below
  const providerErrorBox: { current: ProviderCallError | null } = { current: null };
  let plan: Plan | null = null;
  let planError: string | null = null;
  const executionLog: CallLogEntry[] = [];
  let abortedAtCall: EpisodeResult["abortedAtCall"] = null;

  const report = await runAsyncEvaluation(cf, "agent", async (api, task) => {
    const state: AgentStateView = {
      customers: api.listCustomers({ status: "active" }).map((customer) => ({
        ...customer,
        tickets: api.listTickets(customer.id),
        invoices: api.listInvoices(customer.id),
      })),
    };
    prompt = buildPrompt(task, state);

    let response;
    try {
      response = await provider.complete({
        prompt,
        model: config.model,
        temperature: config.temperature,
        maxTokens: config.maxTokens,
      });
    } catch (err) {
      providerErrorBox.current =
        err instanceof ProviderCallError
          ? err
          : new ProviderCallError(provider.name, "unknown", err instanceof Error ? err.message : String(err), {
              cause: err,
            });
      return; // no execution; report still produced over untouched state
    }
    rawResponse = response.text;
    usage = response.usage;

    try {
      plan = PlanSchema.parse(extractPlanJson(rawResponse));
    } catch (err) {
      planError = err instanceof z.ZodError ? z.prettifyError(err) : err instanceof Error ? err.message : String(err);
      return;
    }

    for (let index = 0; index < plan.calls.length; index++) {
      const call = plan.calls[index];
      const { method, ...args } = call;
      try {
        executeCall(api, call);
        executionLog.push({ index, method, args, ok: true });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        executionLog.push({ index, method, args, ok: false, error: message });
        abortedAtCall = { index, method, error: message };
        break; // first invalid call aborts the rest; the episode still reports normally
      }
    }
  });

  const endedAt = new Date();
  const providerError = providerErrorBox.current;
  const outcome = classifyEpisode({
    providerError,
    planParsed: plan !== null,
    domainApiRejected: abortedAtCall !== null,
    violations: report.violations,
  });

  return {
    outcome,
    plan,
    planError,
    providerError: providerError ? { kind: providerError.kind, message: providerError.message } : null,
    executionLog,
    executedCalls: executionLog.filter((entry) => entry.ok).length,
    abortedAtCall,
    violations: report.violations,
    report,
    prompt,
    rawResponse,
    model: config.model,
    usage,
    wallMs: endedAt.getTime() - startedAt.getTime(),
    startedAt: startedAt.toISOString(),
    endedAt: endedAt.toISOString(),
  };
}
