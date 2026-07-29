import type { Intervention } from "../domain-api";
import type { Customer } from "../schemas";

// The overfit shortcut: groups by exact name, trusts the lowest id, and only
// knows one duplicated invoice number. Passes the original incident, breaks on
// every counterfactual.
export const naiveIntervention: Intervention = (api) => {
  const DUPLICATED_INVOICE_NUMBER = "INV-5001";
  const reason = "duplicate customer merge";

  const groups = new Map<string, Customer[]>();
  for (const customer of api.listCustomers({ status: "active" })) {
    const group = groups.get(customer.name) ?? [];
    group.push(customer);
    groups.set(customer.name, group);
  }

  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const ordered = [...group].sort((a, b) => a.id - b.id);
    const canonical = ordered[0];

    for (const loser of ordered.slice(1)) {
      const voidedInvoiceIds: number[] = [];
      for (const invoice of api.listInvoices(loser.id)) {
        if (invoice.number === DUPLICATED_INVOICE_NUMBER && invoice.status !== "void") {
          api.voidInvoice(invoice.id, reason);
          voidedInvoiceIds.push(invoice.id);
        }
      }

      const transferredTicketIds: number[] = [];
      for (const ticket of api.listTickets(loser.id)) {
        api.transferTicket(ticket.id, canonical.id);
        transferredTicketIds.push(ticket.id);
      }

      const transferredInvoiceIds: number[] = [];
      for (const invoice of api.listInvoices(loser.id)) {
        if (invoice.status === "void") continue;
        api.transferInvoice(invoice.id, canonical.id);
        transferredInvoiceIds.push(invoice.id);
      }

      api.deactivateCustomer(loser.id, reason);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: loser.id,
        details: {
          canonical_customer_id: canonical.id,
          deactivated_customer_id: loser.id,
          transferred_ticket_ids: transferredTicketIds.sort((a, b) => a - b),
          transferred_invoice_ids: transferredInvoiceIds.sort((a, b) => a - b),
          voided_invoice_ids: voidedInvoiceIds.sort((a, b) => a - b),
          reason,
        },
      });
    }
  }
};
