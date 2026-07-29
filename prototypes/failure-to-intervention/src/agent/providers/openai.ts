import OpenAI, { APIConnectionError, APIConnectionTimeoutError, APIError } from "openai";
import type { ResolvedAgentConfig } from "../config";
import {
  ProviderCallError,
  type CompletionRequest,
  type CompletionResponse,
  type ProviderDriver,
} from "./types";

interface OpenAiCompatibleOptions {
  provider: string;
  envKey: string;
  baseURL?: string;
}

const makeErrorMapper =
  (provider: string) =>
  (err: unknown): ProviderCallError => {
    if (err instanceof APIConnectionTimeoutError) {
      return new ProviderCallError(provider, "timeout", err.message, { cause: err });
    }
    if (err instanceof APIConnectionError) {
      return new ProviderCallError(provider, "network", err.message, { cause: err });
    }
    if (err instanceof APIError) {
      const kind = err.status === 429 ? "rate-limit" : err.status === 401 || err.status === 403 ? "auth" : "unknown";
      return new ProviderCallError(provider, kind, `HTTP ${err.status}: ${err.message}`, { cause: err });
    }
    return new ProviderCallError(provider, "unknown", err instanceof Error ? err.message : String(err), {
      cause: err,
    });
  };

export function createOpenAiCompatibleDriver(
  _config: ResolvedAgentConfig,
  options: OpenAiCompatibleOptions,
  injected?: { client?: OpenAI },
): ProviderDriver {
  const client =
    injected?.client ??
    (() => {
      const apiKey = process.env[options.envKey];
      if (!apiKey) throw new Error(`${options.provider} provider requires ${options.envKey} in the environment`);
      return new OpenAI({ apiKey, ...(options.baseURL ? { baseURL: options.baseURL } : {}) });
    })();
  const mapError = makeErrorMapper(options.provider);

  return {
    name: options.provider,
    async complete(req: CompletionRequest): Promise<CompletionResponse> {
      try {
        const completion = await client.chat.completions.create({
          model: req.model,
          messages: [{ role: "user", content: req.prompt }],
          temperature: req.temperature,
          max_completion_tokens: req.maxTokens,
        });
        return {
          text: completion.choices[0]?.message.content ?? "",
          usage: completion.usage
            ? {
                inputTokens: completion.usage.prompt_tokens,
                outputTokens: completion.usage.completion_tokens,
              }
            : undefined,
        };
      } catch (err) {
        throw mapError(err);
      }
    },
  };
}

export function createOpenAiDriver(
  config: ResolvedAgentConfig,
  injected?: { client?: OpenAI },
): ProviderDriver {
  return createOpenAiCompatibleDriver(config, { provider: "openai", envKey: "OPENAI_API_KEY" }, injected);
}
