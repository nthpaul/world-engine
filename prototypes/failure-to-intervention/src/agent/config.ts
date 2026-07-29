import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { z } from "zod";

export const PROVIDER_NAMES = ["anthropic", "openai", "openrouter", "ollama", "cursor"] as const;
export type ProviderName = (typeof PROVIDER_NAMES)[number];

export interface ResolvedAgentConfig {
  provider: ProviderName;
  model: string;
  temperature: number;
  maxTokens: number;
}

const AgentConfigFileSchema = z.object({
  provider: z.string(),
  providers: z.record(z.string(), z.object({ model: z.string() })),
  temperature: z.number(),
  max_tokens: z.number().int().positive(),
});

const DEFAULT_CONFIG_PATH = fileURLToPath(new URL("../../agent.config.json", import.meta.url));

const isProviderName = (name: string): name is ProviderName =>
  (PROVIDER_NAMES as readonly string[]).includes(name);

export function loadAgentConfig(path: string = DEFAULT_CONFIG_PATH): ResolvedAgentConfig {
  const file = AgentConfigFileSchema.parse(JSON.parse(readFileSync(path, "utf8")));
  const providerName = process.env.PROVIDER ?? file.provider;
  if (!isProviderName(providerName)) {
    throw new Error(
      `unknown provider ${JSON.stringify(providerName)}; valid providers: ${PROVIDER_NAMES.join(", ")}`,
    );
  }
  const entry = file.providers[providerName];
  if (!entry) {
    throw new Error(`provider ${JSON.stringify(providerName)} has no entry under "providers" in ${path}`);
  }
  return {
    provider: providerName,
    model: entry.model,
    temperature: file.temperature,
    maxTokens: file.max_tokens,
  };
}
