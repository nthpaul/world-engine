import type { ResolvedAgentConfig } from "../config";
import {
  ProviderCallError,
  type CompletionRequest,
  type CompletionResponse,
  type ProviderDriver,
} from "./types";

const DEFAULT_BASE_URL = "http://localhost:11434";

interface OllamaChatResponse {
  message?: { content?: string };
  prompt_eval_count?: number;
  eval_count?: number;
}

const toProviderCallError = (err: unknown): ProviderCallError => {
  // undici surfaces connection failures as TypeError ("fetch failed")
  if (err instanceof TypeError) {
    return new ProviderCallError("ollama", "network", err.message, { cause: err });
  }
  return new ProviderCallError("ollama", "unknown", err instanceof Error ? err.message : String(err), {
    cause: err,
  });
};

export function createOllamaDriver(
  _config: ResolvedAgentConfig,
  injected?: { fetch?: typeof fetch },
): ProviderDriver {
  const fetchImpl = injected?.fetch ?? fetch;
  const baseUrl = (process.env.OLLAMA_HOST ?? DEFAULT_BASE_URL).replace(/\/+$/, "");

  return {
    name: "ollama",
    async complete(req: CompletionRequest): Promise<CompletionResponse> {
      let res: Response;
      try {
        res = await fetchImpl(`${baseUrl}/api/chat`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            model: req.model,
            messages: [{ role: "user", content: req.prompt }],
            stream: false,
            options: { temperature: req.temperature },
          }),
        });
      } catch (err) {
        throw toProviderCallError(err);
      }
      if (!res.ok) {
        const kind = res.status === 429 ? "rate-limit" : res.status === 401 || res.status === 403 ? "auth" : "unknown";
        throw new ProviderCallError("ollama", kind, `ollama responded HTTP ${res.status}`);
      }
      const body = (await res.json()) as OllamaChatResponse;
      return {
        text: body.message?.content ?? "",
        usage:
          body.prompt_eval_count === undefined && body.eval_count === undefined
            ? undefined
            : { inputTokens: body.prompt_eval_count, outputTokens: body.eval_count },
      };
    },
  };
}
