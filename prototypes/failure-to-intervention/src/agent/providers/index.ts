import { PROVIDER_NAMES, type ResolvedAgentConfig } from "../config";
import type { ProviderDriver } from "./types";

export async function createProvider(config: ResolvedAgentConfig): Promise<ProviderDriver> {
  switch (config.provider) {
    case "anthropic": {
      const { createAnthropicDriver } = await import("./anthropic");
      return createAnthropicDriver(config);
    }
    case "openai": {
      const { createOpenAiDriver } = await import("./openai");
      return createOpenAiDriver(config);
    }
    case "openrouter": {
      const { createOpenRouterDriver } = await import("./openrouter");
      return createOpenRouterDriver(config);
    }
    case "ollama": {
      const { createOllamaDriver } = await import("./ollama");
      return createOllamaDriver(config);
    }
    case "cursor": {
      const { createCursorDriver } = await import("./cursor");
      return createCursorDriver(config);
    }
    default: {
      const unknown: never = config.provider;
      throw new Error(`unknown provider ${JSON.stringify(unknown)}; valid providers: ${PROVIDER_NAMES.join(", ")}`);
    }
  }
}
