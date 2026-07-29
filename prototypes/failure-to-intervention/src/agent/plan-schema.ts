import { z } from "zod";

export const CallSchema = z.discriminatedUnion("method", [
  z.object({
    method: z.literal("transferTicket"),
    ticketId: z.number().int(),
    toCustomerId: z.number().int(),
  }),
  z.object({
    method: z.literal("transferInvoice"),
    invoiceId: z.number().int(),
    toCustomerId: z.number().int(),
  }),
  z.object({
    method: z.literal("voidInvoice"),
    invoiceId: z.number().int(),
    reason: z.string(),
  }),
  z.object({
    method: z.literal("deactivateCustomer"),
    customerId: z.number().int(),
    reason: z.string(),
  }),
  z.object({
    method: z.literal("writeAuditEvent"),
    action: z.string(),
    entityType: z.literal("customer"),
    entityId: z.number().int(),
    details: z.record(z.string(), z.unknown()),
  }),
]);

export const PlanSchema = z.object({
  calls: z.array(CallSchema).max(50),
});

export type PlanCall = z.infer<typeof CallSchema>;
export type Plan = z.infer<typeof PlanSchema>;
