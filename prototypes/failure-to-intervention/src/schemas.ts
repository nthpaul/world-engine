import { z } from "zod";

export const CustomerSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  email: z.string(),
  created_at: z.string(),
  status: z.enum(["active", "deactivated"]),
});

export const TicketSchema = z.object({
  id: z.number().int(),
  customer_id: z.number().int(),
  subject: z.string(),
  status: z.enum(["open", "closed"]),
  created_at: z.string(),
});

export const InvoiceSchema = z.object({
  id: z.number().int(),
  customer_id: z.number().int(),
  number: z.string(),
  amount_cents: z.number().int(),
  issued_at: z.string(),
  status: z.enum(["open", "paid", "void"]),
});

export const AuditEventSchema = z.object({
  id: z.number().int(),
  actor: z.string(),
  action: z.string(),
  entity_type: z.string(),
  entity_id: z.number().int(),
  details: z.string(),
  created_at: z.string(),
});

export const SeedSchema = z.object({
  customers: z.array(CustomerSchema),
  tickets: z.array(TicketSchema),
  invoices: z.array(InvoiceSchema),
  audit_events: z.array(AuditEventSchema),
});

export const TraceSchema = z.object({
  case_id: z.string(),
  kind: z.enum(["incident", "counterfactual"]),
  description: z.string(),
  incident: z.object({
    summary: z.string(),
    observed_at: z.string(),
  }),
  task: z.object({
    issued_at: z.string(),
    objective: z.string(),
    constraints: z.array(z.string()),
  }),
  seed: SeedSchema,
});

export const ViolationSchema = z.object({
  invariant: z.string(),
  message: z.string(),
  details: z.unknown().optional(),
});

export const ReportSchema = z.object({
  case_id: z.string(),
  intervention: z.string(),
  passed: z.boolean(),
  violations: z.array(ViolationSchema),
  initial_digest: z.string(),
  final_digest: z.string(),
  checked_at: z.string(),
});

export type Customer = z.infer<typeof CustomerSchema>;
export type Ticket = z.infer<typeof TicketSchema>;
export type Invoice = z.infer<typeof InvoiceSchema>;
export type AuditEvent = z.infer<typeof AuditEventSchema>;
export type Seed = z.infer<typeof SeedSchema>;
export type Trace = z.infer<typeof TraceSchema>;
export type Violation = z.infer<typeof ViolationSchema>;
export type EvaluationReport = z.infer<typeof ReportSchema>;
