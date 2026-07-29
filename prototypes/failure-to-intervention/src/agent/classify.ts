import type { Violation } from "../schemas";
import type { ProviderCallError } from "./providers/types";

export type EpisodeOutcome =
  | "pass"
  | "business-violation"
  | "invalid-action"
  | "malformed-output"
  | "infrastructure";

export interface ClassifyInput {
  providerError: ProviderCallError | null;
  planParsed: boolean;
  domainApiRejected: boolean;
  violations: Violation[];
}

export function classifyEpisode(input: ClassifyInput): EpisodeOutcome {
  if (input.providerError) return "infrastructure";
  if (!input.planParsed) return "malformed-output";
  if (input.domainApiRejected) return "invalid-action";
  if (input.violations.length > 0) return "business-violation";
  return "pass";
}
