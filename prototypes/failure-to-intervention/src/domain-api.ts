import type { Database } from "./db";
import type { Customer, Invoice, Ticket } from "./schemas";
import type { Task } from "./task";

export interface DomainApi {
  listCustomers(filter?: { status?: "active" | "deactivated" }): Customer[];
  listTickets(customerId: number): Ticket[];
  listInvoices(customerId: number): Invoice[];
  transferTicket(ticketId: number, toCustomerId: number): void;
  transferInvoice(invoiceId: number, toCustomerId: number): void;
  voidInvoice(invoiceId: number, reason: string): void;
  deactivateCustomer(customerId: number, reason: string): void;
  writeAuditEvent(e: {
    action: string;
    entityType: "customer";
    entityId: number;
    details: Record<string, unknown>;
  }): void;
  now(): string;
}

export type Intervention = (api: DomainApi, task: Task) => void;

export function createDomainApi(db: Database, clock: () => string): DomainApi {
  const getCustomer = (id: number): Customer | undefined =>
    db.prepare("SELECT * FROM customers WHERE id = ?").get(id) as Customer | undefined;

  const requireActiveCustomer = (id: number): Customer => {
    const customer = getCustomer(id);
    if (!customer) throw new Error(`customer ${id} does not exist`);
    if (customer.status !== "active") {
      throw new Error(`customer ${id} is not active (status: ${customer.status})`);
    }
    return customer;
  };

  return {
    listCustomers(filter) {
      if (filter?.status) {
        return db
          .prepare("SELECT * FROM customers WHERE status = ? ORDER BY id")
          .all(filter.status) as Customer[];
      }
      return db.prepare("SELECT * FROM customers ORDER BY id").all() as Customer[];
    },

    listTickets(customerId) {
      return db
        .prepare("SELECT * FROM tickets WHERE customer_id = ? ORDER BY id")
        .all(customerId) as Ticket[];
    },

    listInvoices(customerId) {
      return db
        .prepare("SELECT * FROM invoices WHERE customer_id = ? ORDER BY id")
        .all(customerId) as Invoice[];
    },

    transferTicket(ticketId, toCustomerId) {
      const ticket = db.prepare("SELECT * FROM tickets WHERE id = ?").get(ticketId) as
        | Ticket
        | undefined;
      if (!ticket) throw new Error(`ticket ${ticketId} does not exist`);
      requireActiveCustomer(toCustomerId);
      db.prepare("UPDATE tickets SET customer_id = ? WHERE id = ?").run(toCustomerId, ticketId);
    },

    transferInvoice(invoiceId, toCustomerId) {
      const invoice = db.prepare("SELECT * FROM invoices WHERE id = ?").get(invoiceId) as
        | Invoice
        | undefined;
      if (!invoice) throw new Error(`invoice ${invoiceId} does not exist`);
      requireActiveCustomer(toCustomerId);
      db.prepare("UPDATE invoices SET customer_id = ? WHERE id = ?").run(toCustomerId, invoiceId);
    },

    // reason has no column on invoices; callers record it in the merge audit event
    voidInvoice(invoiceId, _reason) {
      const invoice = db.prepare("SELECT * FROM invoices WHERE id = ?").get(invoiceId) as
        | Invoice
        | undefined;
      if (!invoice) throw new Error(`invoice ${invoiceId} does not exist`);
      if (invoice.status === "void") throw new Error(`invoice ${invoiceId} is already void`);
      db.prepare("UPDATE invoices SET status = 'void' WHERE id = ?").run(invoiceId);
    },

    deactivateCustomer(customerId, _reason) {
      const customer = getCustomer(customerId);
      if (!customer) throw new Error(`customer ${customerId} does not exist`);
      if (customer.status === "deactivated") {
        throw new Error(`customer ${customerId} is already deactivated`);
      }
      db.prepare("UPDATE customers SET status = 'deactivated' WHERE id = ?").run(customerId);
    },

    writeAuditEvent(e) {
      db.prepare(
        "INSERT INTO audit_events (actor, action, entity_type, entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
      ).run("intervention", e.action, e.entityType, e.entityId, JSON.stringify(e.details), clock());
    },

    now() {
      return clock();
    },
  };
}
