import type OpenAI from "openai";
import type { ResolvedAgentConfig } from "../config";
import { createOpenAiCompatibleDriver } from "./openai";
import type { ProviderDriver } from "./types";

const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";

export function createOpenRouterDriver(
  config: ResolvedAgentConfig,
  injected?: { client?: OpenAI },
): ProviderDriver {
  return createOpenAiCompatibleDriver(
    config,
    { provider: "openrouter", envKey: "OPENROUTER_API_KEY", baseURL: OPENROUTER_BASE_URL },
    injected,
  );
}
