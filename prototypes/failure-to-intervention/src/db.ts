import { createHash } from "node:crypto";
import BetterSqlite3 from "better-sqlite3";
import type { AuditEvent, Customer, Invoice, Seed, Ticket } from "./schemas";

export type Database = BetterSqlite3.Database;

export interface Snapshot {
  customers: Customer[];
  tickets: Ticket[];
  invoices: Invoice[];
  audit_events: AuditEvent[];
}

const DDL = `
CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE tickets (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  subject TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE invoices (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  number TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  issued_at TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  details TEXT NOT NULL,
  created_at TEXT NOT NULL
);
`;

export function reconstruct(seed: Seed): Database {
  const db = new BetterSqlite3(":memory:");
  db.exec(DDL);

  const insertCustomer = db.prepare(
    "INSERT INTO customers (id, name, email, created_at, status) VALUES (?, ?, ?, ?, ?)",
  );
  for (const c of [...seed.customers].sort((a, b) => a.id - b.id)) {
    insertCustomer.run(c.id, c.name, c.email, c.created_at, c.status);
  }

  const insertTicket = db.prepare(
    "INSERT INTO tickets (id, customer_id, subject, status, created_at) VALUES (?, ?, ?, ?, ?)",
  );
  for (const t of [...seed.tickets].sort((a, b) => a.id - b.id)) {
    insertTicket.run(t.id, t.customer_id, t.subject, t.status, t.created_at);
  }

  const insertInvoice = db.prepare(
    "INSERT INTO invoices (id, customer_id, number, amount_cents, issued_at, status) VALUES (?, ?, ?, ?, ?, ?)",
  );
  for (const i of [...seed.invoices].sort((a, b) => a.id - b.id)) {
    insertInvoice.run(i.id, i.customer_id, i.number, i.amount_cents, i.issued_at, i.status);
  }

  const insertAuditEvent = db.prepare(
    "INSERT INTO audit_events (id, actor, action, entity_type, entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
  );
  for (const e of [...seed.audit_events].sort((a, b) => a.id - b.id)) {
    insertAuditEvent.run(e.id, e.actor, e.action, e.entity_type, e.entity_id, e.details, e.created_at);
  }

  return db;
}

export function snapshot(db: Database): Snapshot {
  return {
    customers: db.prepare("SELECT * FROM customers ORDER BY id").all() as Customer[],
    tickets: db.prepare("SELECT * FROM tickets ORDER BY id").all() as Ticket[],
    invoices: db.prepare("SELECT * FROM invoices ORDER BY id").all() as Invoice[],
    audit_events: db.prepare("SELECT * FROM audit_events ORDER BY id").all() as AuditEvent[],
  };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function digest(snap: Snapshot): string {
  return createHash("sha256").update(canonicalJson(snap)).digest("hex");
}
