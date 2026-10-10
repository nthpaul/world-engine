import { z } from "zod";

const configSchema = z.object({
  environment_id: z.string(),
  provider_id: z.string(),
  episodes: z.number(),
  seed: z.number(),
  max_steps: z.number(),
  concurrency: z.number(),
  model: z.string().nullable(),
  allow_paid: z.boolean(),
  timeout_seconds: z.number(),
  label: z.string(),
  evaluation_only: z.boolean().default(false),
});
const runSchema = z.object({
  id: z.string(),
  label: z.string(),
  status: z.enum([
    "queued",
    "running",
    "completed",
    "cancelled",
    "failed",
    "interrupted",
  ]),
  created_at: z.string(),
  updated_at: z.string(),
  config: configSchema,
  total_episodes: z.number(),
  completed_episodes: z.number(),
  passed_episodes: z.number(),
  failed_episodes: z.number(),
  mean_reward: z.number(),
  success_rate: z.number(),
  elapsed_seconds: z.number(),
  steps_per_second: z.number(),
  error: z.string().nullable(),
});
const jsonObject = z.record(z.unknown());
const traceSchema = z.object({
  index: z.number(),
  action: z.object({ tool: z.string(), args: jsonObject }),
  observation: jsonObject,
  result: z
    .object({ ok: z.boolean(), error: z.string().optional() })
    .passthrough(),
  state_hash: z.string(),
  elapsed_ms: z.number(),
  usage: jsonObject,
});
const provenanceSchema = z
  .object({
    schema_version: z.string(),
    environment_id: z.string(),
    environment_version: z.string(),
    grader_version: z.string(),
    environment_code_hash: z.string(),
    grader_code_hash: z.string(),
    policy_hash: z.string(),
    model_digest: z.string().nullable(),
    policy_identity: z.string(),
    lineage_id: z.string().optional(),
  })
  .passthrough();
const episodeSchema = z.object({
  id: z.string(),
  index: z.number(),
  seed: z.number(),
  status: z.enum(["completed", "failed", "cancelled"]),
  reward: z.number(),
  passed: z.boolean(),
  steps: z.number(),
  elapsed_seconds: z.number(),
  error: z.string().nullable(),
  grader: z.object({
    checks: z.array(
      z.object({ name: z.string(), passed: z.boolean(), detail: z.string() }),
    ),
    reward: z.number(),
    passed: z.boolean(),
  }),
  initial_observation: jsonObject,
  final_observation: jsonObject,
  trace: z.array(traceSchema),
  final_state_hash: z.string(),
  split: z.enum(["train", "validation", "test"]),
  scenario_id: z.string(),
  lineage_id: z.string().optional(),
  provenance: provenanceSchema,
  termination: z.enum([
    "finished",
    "max_steps",
    "timeout",
    "cancelled",
    "provider_error",
    "internal_error",
  ]),
  invalid_actions: z.number(),
  usage: z.record(z.number()),
});
const environmentSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  version: z.string(),
  tools: z.array(
    z.object({
      name: z.string(),
      description: z.string(),
      args_schema: jsonObject,
    }),
  ),
  tags: z.array(z.string()),
  scenario_count: z.number().optional(),
});
const providerSchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["scripted", "remote", "local"]),
  configured: z.boolean(),
  requires_opt_in: z.boolean(),
  models: z.array(z.string()),
});
export const detailSchema = runSchema.extend({
  episodes: z.array(episodeSchema),
});
export const healthSchema = z.object({
  status: z.literal("ok"),
  version: z.string(),
  execution: z.string(),
  active_runs: z.number(),
  paid_calls_enabled: z.boolean().default(false),
});
export type Run = z.infer<typeof runSchema>;
export type RunDetail = z.infer<typeof detailSchema>;
export type Episode = z.infer<typeof episodeSchema>;
export type Environment = z.infer<typeof environmentSchema>;
export type Provider = z.infer<typeof providerSchema>;
export type RunConfig = z.infer<typeof configSchema>;
export type Health = z.infer<typeof healthSchema>;
export type ExportFormat = "sft" | "dpo" | "grpo" | "traces" | "atif";

async function request<T>(
  path: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = z.object({ detail: z.string() }).safeParse(body);
    throw new Error(
      detail.success
        ? detail.data.detail
        : `API returned ${response.status}. Check the local runtime.`,
    );
  }
  const body: unknown = await response.json();
  const parsed = schema.safeParse(body);
  if (!parsed.success)
    throw new Error(
      `Unexpected API response for ${path}: ${parsed.error.issues[0]?.message ?? "invalid data"}`,
    );
  return parsed.data;
}
export const api = {
  health: () => request("/health", healthSchema),
  environments: () =>
    request(
      "/environments",
      z.object({ environments: z.array(environmentSchema) }),
    ),
  providers: () =>
    request("/providers", z.object({ providers: z.array(providerSchema) })),
  runs: () => request("/runs", z.object({ runs: z.array(runSchema) })),
  run: (id: string) => request(`/runs/${encodeURIComponent(id)}`, detailSchema),
  create: (config: RunConfig) =>
    request("/runs", runSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }),
  cancel: (id: string) =>
    request(`/runs/${encodeURIComponent(id)}/cancel`, runSchema, {
      method: "POST",
    }),
  export: async (id: string, format: ExportFormat, quality: string) => {
    const response = await fetch(
      `/api/runs/${encodeURIComponent(id)}/export?format=${format}&quality=${quality}`,
    );
    if (!response.ok) throw new Error(`Export failed (${response.status})`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${id}-${format}-${quality}.jsonl`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return {
      records: Number(response.headers.get("X-Export-Records") ?? 0),
      skipped: Number(response.headers.get("X-Export-Skipped") ?? 0),
      empty: blob.size === 0,
    };
  },
};
