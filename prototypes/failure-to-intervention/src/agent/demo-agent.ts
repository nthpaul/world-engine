import { fileURLToPath } from "node:url";
import { loadCases } from "../cases";
import { naiveIntervention } from "../interventions/naive";
import { robustIntervention } from "../interventions/robust";
import { runEvaluation } from "../report";
import { priceFor } from "./audit-report";
import type { EpisodeOutcome } from "./classify";
import { loadAgentConfig, type ResolvedAgentConfig } from "./config";
import { createProvider } from "./providers";
import type { ProviderDriver } from "./providers/types";
import { runAgentEvaluation, type AgentRunSummary } from "./runner";

const K = 10;
const EPISODES_DIR = fileURLToPath(new URL("../../episodes", import.meta.url));

const fail = (err: unknown): never => {
  console.error(`demo:agent: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
};

const loadConfigOrExit = (): ResolvedAgentConfig => {
  try {
    return loadAgentConfig();
  } catch (err) {
    return fail(err);
  }
};

const createProviderOrExit = async (config: ResolvedAgentConfig): Promise<ProviderDriver> => {
  try {
    return await createProvider(config);
  } catch (err) {
    return fail(err);
  }
};

const config = loadConfigOrExit();
const provider = await createProviderOrExit(config);

const header = "case".padEnd(24) + "naive".padEnd(8) + "robust".padEnd(8) + "agent";
console.log(header);

const summaries: AgentRunSummary[] = [];
for (const caseFile of loadCases()) {
  const naive = runEvaluation(caseFile, "naive", naiveIntervention);
  const robust = runEvaluation(caseFile, "robust", robustIntervention);
  const summary = await runAgentEvaluation(caseFile, K, {
    provider,
    config,
    episodesDir: EPISODES_DIR,
  });
  summaries.push(summary);
  const agentCell = summary.passRate === null ? "-" : `${summary.counts.pass}/${summary.k - summary.excluded}`;
  console.log(
    caseFile.trace.case_id.padEnd(24) +
      (naive.passed ? "PASS" : "FAIL").padEnd(8) +
      (robust.passed ? "PASS" : "FAIL").padEnd(8) +
      agentCell,
  );
}

console.log("");
console.log("classifications:");
for (const summary of summaries) {
  const parts = (Object.entries(summary.counts) as [EpisodeOutcome, number][])
    .filter(([, n]) => n > 0)
    .map(([outcome, n]) => `${outcome} ${n}`);
  console.log(`- ${summary.case_id}: ${parts.join(", ")}`);
}

const inputTokens = summaries.reduce(
  (a, s) => a + s.episodes.reduce((b, e) => b + (e.usage?.inputTokens ?? 0), 0),
  0,
);
const outputTokens = summaries.reduce(
  (a, s) => a + s.episodes.reduce((b, e) => b + (e.usage?.outputTokens ?? 0), 0),
  0,
);
const price = priceFor(config.model);
const cost = price === null ? null : (inputTokens * price.input + outputTokens * price.output) / 1e6;
console.log("");
console.log(
  `tokens: ${inputTokens} in / ${outputTokens} out; cost estimate: ${
    cost === null ? `n/a (no list price for ${config.model})` : `$${cost.toFixed(4)} (list prices, verify before trusting)`
  }`,
);

console.log("");
console.log("falsification rules (decided before the run):");
console.log('- 10/10 on all four cases → "scenario likely too easy for this model" — escalate counterfactual difficulty; do not declare victory.');
console.log("- Failures dominated by malformed-output/schema friction → harness or prompt bug; fix and rerun; not an agent result.");
console.log("- business-violation failures → genuine agent finding; the transcript becomes a candidate failure trace for the next counterfactual family.");
console.log("");
console.log("tsx src/agent/audit-report.ts regenerates audit-data.json from episodes/.");
