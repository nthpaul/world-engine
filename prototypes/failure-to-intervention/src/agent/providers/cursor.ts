import {
  Agent,
  AuthenticationError,
  NetworkError,
  RateLimitError,
  type RunResult,
} from "@cursor/sdk";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ResolvedAgentConfig } from "../config";
import {
  ProviderCallError,
  type CompletionRequest,
  type CompletionResponse,
  type ProviderDriver,
} from "./types";

export interface CursorPromptOptions {
  apiKey?: string;
  model: { id: string };
  local: { cwd: string };
}

export type CursorPromptFn = (prompt: string, options: CursorPromptOptions) => Promise<RunResult>;

const toProviderCallError = (err: unknown): ProviderCallError => {
  if (err instanceof AuthenticationError) {
    return new ProviderCallError("cursor", "auth", err.message, { cause: err });
  }
  if (err instanceof RateLimitError) {
    return new ProviderCallError("cursor", "rate-limit", err.message, { cause: err });
  }
  if (err instanceof NetworkError) {
    return new ProviderCallError("cursor", "network", err.message, { cause: err });
  }
  return new ProviderCallError("cursor", "unknown", err instanceof Error ? err.message : String(err), {
    cause: err,
  });
};

export function createCursorDriver(
  _config: ResolvedAgentConfig,
  injected?: { prompt?: CursorPromptFn },
): ProviderDriver {
  let apiKey: string | undefined;
  if (!injected?.prompt) {
    apiKey = process.env.CURSOR_API_KEY;
    if (!apiKey) throw new Error("cursor provider requires CURSOR_API_KEY in the environment");
  }

  return {
    name: "cursor",
    async complete(req: CompletionRequest): Promise<CompletionResponse> {
      // the Cursor runtime is agentic; a fresh empty cwd gives it nothing to act on
      const cwd = mkdtempSync(join(tmpdir(), "world-engine-cursor-"));
      try {
        const options: CursorPromptOptions = { model: { id: req.model }, local: { cwd } };
        if (apiKey) options.apiKey = apiKey;
        const run = injected?.prompt
          ? await injected.prompt(req.prompt, options)
          : await Agent.prompt(req.prompt, options);
        if (run.status !== "finished") {
          throw new ProviderCallError(
            "cursor",
            "unknown",
            `cursor run ended with status ${JSON.stringify(run.status)}${run.error ? `: ${run.error.message}` : ""}`,
          );
        }
        // token usage is not exposed on the one-shot Agent.prompt path
        return { text: run.result ?? "", usage: undefined };
      } catch (err) {
        if (err instanceof ProviderCallError) throw err;
        throw toProviderCallError(err);
      } finally {
        rmSync(cwd, { recursive: true, force: true });
      }
    },
  };
}
