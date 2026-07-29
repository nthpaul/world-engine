import type { Customer, Invoice, Ticket } from "../schemas";
import type { Task } from "../task";

export interface AgentStateCustomer extends Customer {
  tickets: Ticket[];
  invoices: Invoice[];
}

export interface AgentStateView {
  customers: AgentStateCustomer[];
}

export const PROMPT_TEMPLATE = `You are an operations agent working on a customer database through a constrained API.

{{RUNBOOK}}

## Task

{{OBJECTIVE}}

Constraints:
{{CONSTRAINTS}}

## Current state

Active customers, each with their tickets and invoices:

{{STATE_JSON}}

## What to output

{{OUTPUT_SCHEMA}}`;

const RUNBOOK = `## Business runbook: merging duplicate customers

- Two active customers are a duplicate pair when their normalized emails match.
  Normalize an email by trimming whitespace and lowercasing it.
- The canonical customer in a pair is the one with the earliest created_at.
- An invoice is genuinely duplicated when the pair holds two non-void copies
  with the same number and the same amount_cents. The copy on the canonical
  customer survives; if the canonical customer holds no copy, the
  earliest-issued copy survives. Void every non-surviving copy.
- Void is not transfer: a voided invoice stays on the customer it was on.
- Deactivate each duplicate customer. Never delete anything.
- Move each duplicate's tickets and remaining non-void invoices to the
  canonical customer.
- Customers outside every duplicate pair, and their tickets and invoices,
  must not change.
- Write exactly one audit event per deactivated duplicate:
  - action: "customer.dedup.merge"
  - entityType: "customer"
  - entityId: the deactivated duplicate's id
  - details keys:
    - canonical_customer_id: the canonical customer's id
    - deactivated_customer_id: the deactivated duplicate's id
    - transferred_ticket_ids: sorted array of ticket ids moved to the canonical customer
    - transferred_invoice_ids: sorted array of invoice ids moved to the canonical customer
    - voided_invoice_ids: sorted array of invoice ids voided on the duplicate
    - reason: a short string explaining the merge`;

const OUTPUT_SCHEMA = `Respond with JSON only: one JSON object, no prose, no markdown fences.

{ "calls": [ <call>, ... ] }

Each call is executed in the order you list it. At most 50 calls. The five
methods and their arguments:

{ "method": "transferTicket", "ticketId": <int>, "toCustomerId": <int> }
{ "method": "transferInvoice", "invoiceId": <int>, "toCustomerId": <int> }
{ "method": "voidInvoice", "invoiceId": <int>, "reason": <string> }
{ "method": "deactivateCustomer", "customerId": <int>, "reason": <string> }
{ "method": "writeAuditEvent", "action": <string>, "entityType": "customer", "entityId": <int>, "details": <object> }

Read the state, decide the full merge, and emit every call needed to complete it.`;

export function buildPrompt(task: Task, state: AgentStateView): string {
  const constraints = task.constraints.map((c) => `- ${c}`).join("\n");
  return PROMPT_TEMPLATE.replace("{{RUNBOOK}}", RUNBOOK)
    .replace("{{OBJECTIVE}}", task.objective)
    .replace("{{CONSTRAINTS}}", constraints)
    .replace("{{STATE_JSON}}", JSON.stringify(state, null, 2))
    .replace("{{OUTPUT_SCHEMA}}", OUTPUT_SCHEMA);
}
