import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";
import type { CaseFile } from "../cases";
import { ViolationSchema } from "../schemas";
import type { EpisodeOutcome } from "./classify";
import type { ResolvedAgentConfig } from "./config";
import { runAgentEpisode, type EpisodeResult } from "./driver";
import { PlanSchema } from "./plan-schema";
import type { ProviderDriver } from "./providers/types";

export const TranscriptSchema = z.object({
  case_id: z.string(),
  index: z.number().int(),
  outcome: z.enum(["pass", "business-violation", "invalid-action", "malformed-output", "infrastructure"]),
  prompt: z.string(),
  rawResponse: z.string().nullable(),
  plan: PlanSchema.nullable(),
  planError: z.string().nullable(),
  executionLog: z.array(
    z.object({
      index: z.number().int(),
      method: z.string(),
      args: z.record(z.string(), z.unknown()),
      ok: z.boolean(),
      error: z.string().optional(),
    }),
  ),
  executedCalls: z.number().int(),
  violations: z.array(ViolationSchema),
  model: z.string(),
  usage: z
    .object({ inputTokens: z.number().optional(), outputTokens: z.number().optional() })
    .optional(),
  wallMs: z.number(),
  startedAt: z.string(),
  endedAt: z.string(),
});

export type Transcript = z.infer<typeof TranscriptSchema>;

export interface AgentRunSummary {
  case_id: string;
  k: number;
  counts: Record<EpisodeOutcome, number>;
  passRate: number | null;
  excluded: number;
  episodes: EpisodeResult[];
}

const toTranscript = (caseId: string, index: number, episode: EpisodeResult): Transcript => ({
  case_id: caseId,
  index,
  outcome: episode.outcome,
  prompt: episode.prompt,
  rawResponse: episode.rawResponse,
  plan: episode.plan,
  planError: episode.planError,
  executionLog: episode.executionLog,
  executedCalls: episode.executedCalls,
  violations: episode.violations,
  model: episode.model,
  usage: episode.usage,
  wallMs: episode.wallMs,
  startedAt: episode.startedAt,
  endedAt: episode.endedAt,
});

export function writeTranscript(episodesDir: string, caseId: string, index: number, episode: EpisodeResult): string {
  const dir = join(episodesDir, caseId);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, `episode-${index}.json`);
  writeFileSync(path, JSON.stringify(TranscriptSchema.parse(toTranscript(caseId, index, episode)), null, 2));
  return path;
}

export async function runAgentEvaluation(
  cf: CaseFile,
  k: number,
  deps: { provider: ProviderDriver; config: ResolvedAgentConfig; episodesDir?: string },
): Promise<AgentRunSummary> {
  const counts: Record<EpisodeOutcome, number> = {
    pass: 0,
    "business-violation": 0,
    "invalid-action": 0,
    "malformed-output": 0,
    infrastructure: 0,
  };
  const episodes: EpisodeResult[] = [];

  for (let index = 0; index < k; index++) {
    let episode = await runAgentEpisode(cf, deps.provider, deps.config);
    if (episode.outcome === "infrastructure") {
      episode = await runAgentEpisode(cf, deps.provider, deps.config); // retried once, then excluded
    }
    counts[episode.outcome]++;
    episodes.push(episode);
    if (deps.episodesDir) writeTranscript(deps.episodesDir, cf.trace.case_id, index, episode);
  }

  const excluded = counts.infrastructure;
  const denominator = k - excluded;
  return {
    case_id: cf.trace.case_id,
    k,
    counts,
    passRate: denominator === 0 ? null : counts.pass / denominator,
    excluded,
    episodes,
  };
}
