import { mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
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
  attempts: z.number().int().positive(),
  infraErrors: z.array(z.object({ attempt: z.number().int(), kind: z.string(), message: z.string() })),
});

export type Transcript = z.infer<typeof TranscriptSchema>;

export interface AgentRunSummary {
  case_id: string;
  k: number;
  counts: Record<EpisodeOutcome, number>;
  passRate: number | null;
  excluded: number;
  infraRetries: number;
  episodes: EpisodeResult[];
}

export interface EpisodeAttempts {
  attempts: number;
  infraErrors: { attempt: number; kind: string; message: string }[];
}

const toTranscript = (
  caseId: string,
  index: number,
  episode: EpisodeResult,
  episodeAttempts: EpisodeAttempts,
): Transcript => ({
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
  attempts: episodeAttempts.attempts,
  infraErrors: episodeAttempts.infraErrors,
});

export function writeTranscript(
  episodesDir: string,
  caseId: string,
  index: number,
  episode: EpisodeResult,
  episodeAttempts: EpisodeAttempts,
): string {
  const dir = join(episodesDir, caseId);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, `episode-${index}.json`);
  writeFileSync(
    path,
    JSON.stringify(TranscriptSchema.parse(toTranscript(caseId, index, episode, episodeAttempts)), null, 2),
  );
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
  let infraRetries = 0;

  if (deps.episodesDir) {
    // smaller-k reruns must not leak stale transcripts into the audit
    const dir = join(deps.episodesDir, cf.trace.case_id);
    mkdirSync(dir, { recursive: true });
    for (const file of readdirSync(dir)) {
      if (/^episode-\d+\.json$/.test(file)) rmSync(join(dir, file));
    }
  }

  for (let index = 0; index < k; index++) {
    const episodeAttempts: EpisodeAttempts = { attempts: 1, infraErrors: [] };
    let episode = await runAgentEpisode(cf, deps.provider, deps.config);
    if (episode.outcome === "infrastructure") {
      if (episode.providerError) {
        episodeAttempts.infraErrors.push({ attempt: 1, ...episode.providerError });
      }
      episode = await runAgentEpisode(cf, deps.provider, deps.config); // retried once, then excluded
      episodeAttempts.attempts = 2;
      if (episode.outcome === "infrastructure") {
        if (episode.providerError) {
          episodeAttempts.infraErrors.push({ attempt: 2, ...episode.providerError });
        }
      } else {
        infraRetries++;
      }
    }
    counts[episode.outcome]++;
    episodes.push(episode);
    if (deps.episodesDir) writeTranscript(deps.episodesDir, cf.trace.case_id, index, episode, episodeAttempts);
  }

  const excluded = counts.infrastructure;
  const denominator = k - excluded;
  return {
    case_id: cf.trace.case_id,
    k,
    counts,
    passRate: denominator === 0 ? null : counts.pass / denominator,
    excluded,
    infraRetries,
    episodes,
  };
}
