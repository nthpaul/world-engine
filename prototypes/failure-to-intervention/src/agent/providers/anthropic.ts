import Anthropic, { APIConnectionError, APIConnectionTimeoutError, APIError } from "@anthropic-ai/sdk";
import type { ResolvedAgentConfig } from "../config";
import {
  ProviderCallError,
  type CompletionRequest,
  type CompletionResponse,
  type ProviderDriver,
} from "./types";

const toProviderCallError = (err: unknown): ProviderCallError => {
  if (err instanceof APIConnectionTimeoutError) {
    return new ProviderCallError("anthropic", "timeout", err.message, { cause: err });
  }
  if (err instanceof APIConnectionError) {
    return new ProviderCallError("anthropic", "network", err.message, { cause: err });
  }
  if (err instanceof APIError) {
    const kind = err.status === 429 ? "rate-limit" : err.status === 401 || err.status === 403 ? "auth" : "unknown";
    return new ProviderCallError("anthropic", kind, `HTTP ${err.status}: ${err.message}`, { cause: err });
  }
  return new ProviderCallError("anthropic", "unknown", err instanceof Error ? err.message : String(err), {
    cause: err,
  });
};

export function createAnthropicDriver(
  _config: ResolvedAgentConfig,
  injected?: { client?: Anthropic },
): ProviderDriver {
  const client =
    injected?.client ??
    (() => {
      const apiKey = process.env.ANTHROPIC_API_KEY;
      if (!apiKey) throw new Error("anthropic provider requires ANTHROPIC_API_KEY in the environment");
      return new Anthropic({ apiKey });
    })();

  return {
    name: "anthropic",
    async complete(req: CompletionRequest): Promise<CompletionResponse> {
      try {
        const message = await client.messages.create({
          model: req.model,
          max_tokens: req.maxTokens,
          temperature: req.temperature,
          messages: [{ role: "user", content: req.prompt }],
        });
        return {
          text: message.content.map((block) => (block.type === "text" ? block.text : "")).join(""),
          usage: {
            inputTokens: message.usage.input_tokens ?? undefined,
            outputTokens: message.usage.output_tokens,
          },
        };
      } catch (err) {
        throw toProviderCallError(err);
      }
    },
  };
}
