import type { Intervention } from "../domain-api";
import type { Customer, Invoice } from "../schemas";

const normalizeEmail = (email: string) => email.trim().toLowerCase();

// Derives everything from live state: normalized-email grouping, canonical by
// earliest created_at, duplicated invoices by number+amount within the pair.
export const robustIntervention: Intervention = (api) => {
  const reason = "duplicate customer merge: shared normalized email";

  const groups = new Map<string, Customer[]>();
  for (const customer of api.listCustomers({ status: "active" })) {
    const key = normalizeEmail(customer.email);
    const group = groups.get(key) ?? [];
    group.push(customer);
    groups.set(key, group);
  }

  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const ordered = [...members].sort(
      (a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id,
    );
    const canonical = ordered[0];
    const duplicates = ordered.slice(1);

    const activeInvoices = members
      .flatMap((m) => api.listInvoices(m.id))
      .filter((i) => i.status !== "void");
    const byNumberAmount = new Map<string, Invoice[]>();
    for (const invoice of activeInvoices) {
      const key = `${invoice.number}::${invoice.amount_cents}`;
      const copies = byNumberAmount.get(key) ?? [];
      copies.push(invoice);
      byNumberAmount.set(key, copies);
    }
    const doomedCopyIds = new Set<number>();
    for (const copies of byNumberAmount.values()) {
      if (copies.length < 2) continue;
      const sortedCopies = [...copies].sort(
        (a, b) => a.issued_at.localeCompare(b.issued_at) || a.id - b.id,
      );
      const survivor =
        sortedCopies.find((i) => i.customer_id === canonical.id) ?? sortedCopies[0];
      for (const copy of copies) {
        if (copy.id !== survivor.id) doomedCopyIds.add(copy.id);
      }
    }

    for (const dup of duplicates) {
      const voidedInvoiceIds: number[] = [];
      for (const invoice of api.listInvoices(dup.id)) {
        if (doomedCopyIds.has(invoice.id)) {
          api.voidInvoice(invoice.id, reason);
          voidedInvoiceIds.push(invoice.id);
        }
      }

      const transferredTicketIds: number[] = [];
      for (const ticket of api.listTickets(dup.id)) {
        api.transferTicket(ticket.id, canonical.id);
        transferredTicketIds.push(ticket.id);
      }

      const transferredInvoiceIds: number[] = [];
      for (const invoice of api.listInvoices(dup.id)) {
        if (invoice.status === "void") continue;
        api.transferInvoice(invoice.id, canonical.id);
        transferredInvoiceIds.push(invoice.id);
      }

      api.deactivateCustomer(dup.id, reason);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: dup.id,
        details: {
          canonical_customer_id: canonical.id,
          deactivated_customer_id: dup.id,
          transferred_ticket_ids: transferredTicketIds.sort((a, b) => a - b),
          transferred_invoice_ids: transferredInvoiceIds.sort((a, b) => a - b),
          voided_invoice_ids: voidedInvoiceIds.sort((a, b) => a - b),
          reason,
        },
      });
    }
  }
};
