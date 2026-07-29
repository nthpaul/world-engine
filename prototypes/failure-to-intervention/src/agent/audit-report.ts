import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { EpisodeOutcome } from "./classify";
import { TranscriptSchema } from "./runner";

const PROTOTYPE_ROOT = fileURLToPath(new URL("../..", import.meta.url));

// USD per 1M tokens; list prices, verify before trusting
const MODEL_PRICES: Record<string, { input: number; output: number }> = {
  "claude-sonnet-4-5-20250929": { input: 3, output: 15 },
  "anthropic/claude-sonnet-4.5": { input: 3, output: 15 },
  "gpt-4.1": { input: 2, output: 8 },
};

export function priceFor(model: string): { input: number; output: number } | null {
  return MODEL_PRICES[model] ?? null;
}

export interface InfraErrorRecord {
  file: string;
  kind: string;
  message: string;
}

export interface CaseAudit {
  case_id: string;
  k: number;
  counts: Record<EpisodeOutcome, number>;
  passRate: number | null;
  excluded: number;
  infraRetries: number;
  infraErrors: InfraErrorRecord[];
  inputTokens: number;
  outputTokens: number;
  costUsd: number | null;
}

export interface EpisodeIndexEntry {
  file: string;
  case_id: string;
  index: number;
  outcome: EpisodeOutcome;
}

export interface AuditData {
  cases: CaseAudit[];
  totals: {
    k: number;
    counts: Record<EpisodeOutcome, number>;
    passRate: number | null;
    excluded: number;
    infraRetries: number;
    infraErrors: InfraErrorRecord[];
    inputTokens: number;
    outputTokens: number;
    costUsd: number | null;
  };
  episodes: EpisodeIndexEntry[];
  generatedAt: string;
}

const emptyCounts = (): Record<EpisodeOutcome, number> => ({
  pass: 0,
  "business-violation": 0,
  "invalid-action": 0,
  "malformed-output": 0,
  infrastructure: 0,
});

interface Bucket {
  counts: Record<EpisodeOutcome, number>;
  infraRetries: number;
  infraErrors: InfraErrorRecord[];
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  pricedEpisodes: number;
}

const emptyBucket = (): Bucket => ({
  counts: emptyCounts(),
  infraRetries: 0,
  infraErrors: [],
  inputTokens: 0,
  outputTokens: 0,
  costUsd: 0,
  pricedEpisodes: 0,
});

export function aggregateEpisodes(episodesDir: string): AuditData {
  const episodes: EpisodeIndexEntry[] = [];
  const byCase = new Map<string, Bucket>();
  const totals = emptyBucket();

  const caseIds = readdirSync(episodesDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  for (const caseId of caseIds) {
    const caseDir = join(episodesDir, caseId);
    const files = readdirSync(caseDir)
      .filter((f) => /^episode-\d+\.json$/.test(f))
      .sort((a, b) => Number(a.match(/\d+/)![0]) - Number(b.match(/\d+/)![0]));
    const bucket = emptyBucket();
    for (const file of files) {
      const path = join(caseDir, file);
      const t = TranscriptSchema.parse(JSON.parse(readFileSync(path, "utf8")));
      for (const b of [bucket, totals]) {
        b.counts[t.outcome]++;
        if (t.attempts > 1) b.infraRetries++;
        for (const err of t.infraErrors) {
          b.infraErrors.push({ file: path, kind: err.kind, message: err.message });
        }
        b.inputTokens += t.usage?.inputTokens ?? 0;
        b.outputTokens += t.usage?.outputTokens ?? 0;
        const price = priceFor(t.model);
        if (price) {
          b.pricedEpisodes++;
          b.costUsd += ((t.usage?.inputTokens ?? 0) * price.input + (t.usage?.outputTokens ?? 0) * price.output) / 1e6;
        }
      }
      episodes.push({ file: path, case_id: t.case_id, index: t.index, outcome: t.outcome });
    }
    byCase.set(caseId, bucket);
  }

  const summarize = (b: Bucket) => {
    const k = Object.values(b.counts).reduce((a, n) => a + n, 0);
    const excluded = b.counts.infrastructure;
    const denominator = k - excluded;
    return {
      k,
      counts: b.counts,
      passRate: denominator === 0 ? null : b.counts.pass / denominator,
      excluded,
      infraRetries: b.infraRetries,
      infraErrors: b.infraErrors,
      inputTokens: b.inputTokens,
      outputTokens: b.outputTokens,
      costUsd: b.pricedEpisodes === 0 ? null : b.costUsd,
    };
  };

  return {
    cases: [...byCase.entries()].map(([case_id, bucket]) => ({ case_id, ...summarize(bucket) })),
    totals: summarize(totals),
    episodes,
    generatedAt: new Date().toISOString(),
  };
}

const isMain = process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const episodesDir = process.argv[2] ?? join(PROTOTYPE_ROOT, "episodes");
  if (!existsSync(episodesDir)) {
    console.error(`audit-report: episodes directory not found: ${episodesDir}`);
    process.exit(1);
  }
  const data = aggregateEpisodes(episodesDir);
  const outPath = join(PROTOTYPE_ROOT, "audit-data.json");
  writeFileSync(outPath, JSON.stringify(data, null, 2));
  console.log(`audit-report: wrote ${outPath} (${data.episodes.length} episodes across ${data.cases.length} cases)`);
}
