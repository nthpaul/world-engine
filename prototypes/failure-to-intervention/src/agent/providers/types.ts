export interface CompletionRequest {
  prompt: string;
  model: string;
  temperature: number;
  maxTokens: number;
}

export interface CompletionUsage {
  inputTokens?: number;
  outputTokens?: number;
}

export interface CompletionResponse {
  text: string;
  usage?: CompletionUsage;
}

export interface ProviderDriver {
  readonly name: string;
  complete(req: CompletionRequest): Promise<CompletionResponse>;
}

export type ProviderCallErrorKind = "network" | "rate-limit" | "timeout" | "auth" | "unknown";

export class ProviderCallError extends Error {
  readonly kind: ProviderCallErrorKind;
  readonly provider: string;

  constructor(provider: string, kind: ProviderCallErrorKind, message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "ProviderCallError";
    this.provider = provider;
    this.kind = kind;
  }
}
