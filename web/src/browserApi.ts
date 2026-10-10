import { z } from "zod";

const digest = z.string().regex(/^[a-f0-9]{64}$/);
const identifier = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/);
export const browserTaskSchema = z.object({
  id: identifier,
  version: z.string(),
  name: z.string(),
  instruction: z.string(),
  application: z.string(),
  application_version: z.string(),
  image_digest: z.string().regex(/^sha256:[a-f0-9]{64}$/),
  fixture_hash: digest,
  grader_version: z.string(),
  observation_mode: z.literal("AX"),
  evaluation_only: z.literal(true),
});
export const browserConfigSchema = z.object({
  task_id: identifier,
  provider_id: z.enum([
    "local-browser",
    "browser-reference",
    "browser-baseline",
  ]),
  model: z.string().min(1).max(160),
  seed: z.number().int().min(0).max(2147483647),
  max_steps: z.number().int().min(1).max(50),
  timeout_seconds: z.number().int().min(30).max(600),
});
export const browserStatusSchema = z.object({
  available: z.boolean(),
  reason: z.string().nullable(),
  active_attempts: z.number().int().nonnegative(),
  max_active_attempts: z.literal(1),
  providers: z.array(
    z.object({
      id: browserConfigSchema.shape.provider_id,
      name: z.string(),
      configured: z.boolean(),
      model: z.string().nullable(),
      models: z.array(z.string()).optional(),
      readiness: z.string().optional(),
    }),
  ),
  paid_calls_enabled: z.literal(false),
});
const gradeSchema = z.object({
  passed: z.boolean(),
  reward: z.union([z.literal(0), z.literal(1)]),
  checks: z.array(
    z.object({ name: z.string(), passed: z.boolean(), detail: z.string() }),
  ),
  grader_version: z.string(),
  sealed_state_sha256: digest,
});
export const browserAttemptSchema = z.object({
  schema: z.literal("world-engine.browser.v1"),
  id: identifier,
  status: z.enum([
    "queued",
    "starting",
    "running",
    "sealing",
    "grading",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
  ]),
  termination: z.string().nullable(),
  config: browserConfigSchema,
  task: browserTaskSchema,
  created_at: z.string(),
  updated_at: z.string(),
  steps: z.number().int().nonnegative(),
  invalid_actions: z.number().int().nonnegative(),
  passed: z.boolean(),
  reward: z.union([z.literal(0), z.literal(1)]),
  provenance: z
    .object({
      evaluation_only: z.literal(true),
      training_eligible: z.literal(false),
    })
    .passthrough(),
  reconciliation_required: z.boolean().optional(),
  journal_finalization_failed: z.literal(true).optional(),
  outcome: gradeSchema.nullable(),
  error: z.string().nullable(),
  elapsed_seconds: z.number().nonnegative(),
  phase_seconds: z.record(z.number().nonnegative()),
  cleanup: z
    .object({
      status: z.enum(["completed", "failed", "timeout"]),
      error_code: z.enum(["cleanup_failed", "cleanup_timeout"]).nullable(),
    })
    .nullable(),
});
export const browserObservationSchema = z.object({
  url: z.string(),
  title: z.string(),
  accessibility_text: z.string(),
  screenshot_artifact_id: z.string(),
  observation_mode: z.literal("AX"),
  image_not_sent_to_model: z.literal(true),
});
export const browserDetailSchema = browserAttemptSchema
  .extend({
    journal: z.array(
      z
        .object({
          schema: z.literal("world-engine.browser.v1"),
          attempt_id: identifier,
          sequence: z.number().int().nonnegative(),
          event: z.string(),
          at: z.string(),
          data: z.record(z.unknown()),
          previous_hash: digest,
          content_hash: digest,
        })
        .passthrough(),
    ),
    artifacts: z.array(
      z.object({
        id: z.string(),
        kind: z.enum(["screenshot", "video", "public_trace"]),
        mime_type: z.enum([
          "image/png",
          "image/jpeg",
          "video/webm",
          "application/x-ndjson",
        ]),
        size_bytes: z.number().int().nonnegative(),
        sha256: digest,
        url: z
          .string()
          .regex(
            /^\/api\/browser\/attempts\/[A-Za-z0-9._-]+\/artifacts\/[A-Za-z0-9._%/-]+$/,
          ),
      }),
    ),
  })
  .superRefine((detail, context) => {
    if (detail.config.task_id !== detail.task.id)
      context.addIssue({ code: "custom", message: "Task identity mismatch" });
    for (const entry of detail.journal) {
      if (entry.attempt_id !== detail.id)
        context.addIssue({
          code: "custom",
          message: "Journal attempt identity mismatch",
        });
      if (
        entry.event === "observation" &&
        !z
          .object({
            observation: browserObservationSchema,
            step: z.number().int().nonnegative(),
          })
          .safeParse(entry.data).success
      )
        context.addIssue({
          code: "custom",
          message: "Invalid recorded observation",
        });
    }
    for (const artifact of detail.artifacts) {
      let relative = "";
      const prefix = `/api/browser/attempts/${detail.id}/artifacts/`;
      try {
        if (artifact.url.startsWith(prefix))
          relative = decodeURIComponent(artifact.url.slice(prefix.length));
      } catch {
        /* Rejected below. */
      }
      if (
        relative !== artifact.id ||
        !relative
          .split("/")
          .every(
            (part) =>
              /^[A-Za-z0-9._-]+$/.test(part) && part !== "." && part !== "..",
          )
      )
        context.addIssue({
          code: "custom",
          message: "Artifact URL identity mismatch",
        });
    }
  });

export type BrowserTask = z.infer<typeof browserTaskSchema>;
export type BrowserConfig = z.infer<typeof browserConfigSchema>;
export type BrowserStatus = z.infer<typeof browserStatusSchema>;
export type BrowserAttempt = z.infer<typeof browserAttemptSchema>;
export type BrowserDetail = z.infer<typeof browserDetailSchema>;
export type BrowserJournalEntry = BrowserDetail["journal"][number];

const recordedInputSchema = z
  .object({
    task: z.string(),
    observation: browserObservationSchema
      .omit({ screenshot_artifact_id: true })
      .extend({ accessibility_truncated: z.boolean() })
      .passthrough(),
    history: z.array(z.record(z.unknown())),
  })
  .passthrough();
export function recordedModelInput(detail: BrowserDetail, sequence: number) {
  const nextObservation = detail.journal.find(
    (entry) => entry.event === "observation" && entry.sequence > sequence,
  );
  const intent = detail.journal.find(
    (entry) =>
      entry.event === "inference_intent" &&
      entry.sequence > sequence &&
      entry.sequence < (nextObservation?.sequence ?? Infinity),
  );
  const envelope = z
    .object({
      request_body: z.object({
        messages: z.array(z.object({ role: z.string(), content: z.string() })),
      }),
    })
    .safeParse(intent?.data);
  const message = envelope.success
    ? envelope.data.request_body.messages.find((entry) => entry.role === "user")
    : undefined;
  if (!message) return null;
  try {
    const content: unknown = JSON.parse(message.content);
    const parsed = recordedInputSchema.safeParse(content);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api/browser${path}`, {
    ...options,
    redirect: "error",
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const error = z.object({ detail: z.string() }).safeParse(body);
    throw new Error(
      error.success
        ? error.data.detail
        : `Browser API request failed (${response.status}).`,
    );
  }
  const body: unknown = await response.json();
  const result = schema.safeParse(body);
  if (!result.success)
    throw new Error("Browser API returned an incompatible response.");
  return result.data;
}

export const browserApi = {
  tasks: (signal?: AbortSignal) =>
    request("/tasks", z.object({ tasks: z.array(browserTaskSchema) }), {
      signal,
    }),
  status: (signal?: AbortSignal) =>
    request("/status", browserStatusSchema, { signal }),
  attempts: (signal?: AbortSignal, offset = 0) =>
    request(
      `/attempts?limit=26&offset=${offset}`,
      z.object({ attempts: z.array(browserAttemptSchema) }),
      { signal },
    ),
  attempt: (id: string, signal?: AbortSignal) =>
    request(`/attempts/${encodeURIComponent(id)}`, browserDetailSchema, {
      signal,
    }),
  create: (config: BrowserConfig) =>
    request("/attempts", browserAttemptSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(browserConfigSchema.parse(config)),
    }),
  cancel: (id: string) =>
    request(
      `/attempts/${encodeURIComponent(id)}/cancel`,
      browserAttemptSchema,
      { method: "POST" },
    ),
};
