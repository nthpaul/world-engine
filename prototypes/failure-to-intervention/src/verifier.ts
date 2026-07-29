import type { Snapshot } from "./db";
import type { Customer, Invoice } from "./schemas";

export interface InvariantViolation {
  invariant: string;
  message: string;
  details?: unknown;
}

interface DupPair {
  emailKey: string;
  canonical: Customer;
  duplicates: Customer[];
  memberIds: Set<number>;
  nonSurvivingDupIds: Set<number>;
}

const normalizeEmail = (email: string) => email.trim().toLowerCase();

// ISO-8601 UTC strings sort correctly by code units; localeCompare would make
// the determinism claim rest on ICU locale data.
const compareIso = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

function derivePairs(initial: Snapshot): DupPair[] {
  const groups = new Map<string, Customer[]>();
  for (const customer of initial.customers) {
    if (customer.status !== "active") continue;
    const key = normalizeEmail(customer.email);
    const group = groups.get(key) ?? [];
    group.push(customer);
    groups.set(key, group);
  }

  const pairs: DupPair[] = [];
  for (const [emailKey, members] of groups) {
    if (members.length < 2) continue;
    const ordered = [...members].sort(
      (a, b) => compareIso(a.created_at, b.created_at) || a.id - b.id,
    );
    const canonical = ordered[0];
    const duplicates = ordered.slice(1);
    const memberIds = new Set(members.map((m) => m.id));

    const activeInvoices = initial.invoices.filter(
      (i) => memberIds.has(i.customer_id) && i.status !== "void",
    );
    const byNumberAmount = new Map<string, Invoice[]>();
    for (const invoice of activeInvoices) {
      const key = `${invoice.number}::${invoice.amount_cents}`;
      const copies = byNumberAmount.get(key) ?? [];
      copies.push(invoice);
      byNumberAmount.set(key, copies);
    }
    const nonSurvivingDupIds = new Set<number>();
    for (const copies of byNumberAmount.values()) {
      if (copies.length < 2) continue;
      const sortedCopies = [...copies].sort(
        (a, b) => compareIso(a.issued_at, b.issued_at) || a.id - b.id,
      );
      const survivor =
        sortedCopies.find((i) => i.customer_id === canonical.id) ?? sortedCopies[0];
      for (const copy of copies) {
        if (copy.id !== survivor.id) nonSurvivingDupIds.add(copy.id);
      }
    }

    pairs.push({ emailKey, canonical, duplicates, memberIds, nonSurvivingDupIds });
  }
  return pairs;
}

function changedFields(a: object, b: object, ignore: string[] = []): string[] {
  const ra = a as unknown as Record<string, unknown>;
  const rb = b as unknown as Record<string, unknown>;
  const changed: string[] = [];
  for (const key of new Set([...Object.keys(ra), ...Object.keys(rb)])) {
    if (ignore.includes(key)) continue;
    const before = JSON.stringify(ra[key]);
    const after = JSON.stringify(rb[key]);
    if (before !== after) changed.push(`${key}: ${before} -> ${after}`);
  }
  return changed;
}

const sortedIds = (rows: { id: number }[]): number[] => rows.map((r) => r.id).sort((a, b) => a - b);

export function verify(initial: Snapshot, final: Snapshot): InvariantViolation[] {
  const violations: InvariantViolation[] = [];
  const viol = (invariant: string, message: string, details?: unknown) =>
    violations.push(details === undefined ? { invariant, message } : { invariant, message, details });

  const pairs = derivePairs(initial);
  const pairOfMember = new Map<number, DupPair>();
  for (const pair of pairs) {
    for (const id of pair.memberIds) pairOfMember.set(id, pair);
  }

  const finalCustomers = new Map(final.customers.map((c) => [c.id, c]));
  const finalTickets = new Map(final.tickets.map((t) => [t.id, t]));
  const finalInvoices = new Map(final.invoices.map((i) => [i.id, i]));

  // single-active-canonical
  for (const pair of pairs) {
    const canonicalFinal = finalCustomers.get(pair.canonical.id);
    if (canonicalFinal && canonicalFinal.status !== "active") {
      viol(
        "single-active-canonical",
        `pair ${pair.emailKey}: canonical customer ${pair.canonical.id} is not active (status: ${canonicalFinal.status})`,
      );
    }
    if (canonicalFinal) {
      const edited = changedFields(pair.canonical, canonicalFinal);
      if (edited.length > 0) {
        viol(
          "single-active-canonical",
          `canonical customer ${pair.canonical.id} was edited (${edited.join(", ")})`,
        );
      }
    }
    for (const dup of pair.duplicates) {
      const dupFinal = finalCustomers.get(dup.id);
      if (dupFinal && dupFinal.status === "active") {
        viol(
          "single-active-canonical",
          `pair ${pair.emailKey}: duplicate customer ${dup.id} is still active`,
        );
      }
    }
  }

  // tickets-preserved-attached
  for (const ticket of initial.tickets) {
    const f = finalTickets.get(ticket.id);
    if (!f) {
      viol("tickets-preserved-attached", `ticket ${ticket.id} is missing in final state`);
      continue;
    }
    const edited = changedFields(ticket, f, ["customer_id"]);
    if (edited.length > 0) {
      viol("tickets-preserved-attached", `ticket ${ticket.id} was edited (${edited.join(", ")})`);
    }
    const pair = pairOfMember.get(ticket.customer_id);
    if (pair && f.customer_id !== pair.canonical.id) {
      viol(
        "tickets-preserved-attached",
        `ticket ${ticket.id} should be attached to canonical customer ${pair.canonical.id} but is on customer ${f.customer_id}`,
      );
    }
  }

  // invoices-preserved-only-dup-voided
  for (const invoice of initial.invoices) {
    const f = finalInvoices.get(invoice.id);
    if (!f) {
      viol(
        "invoices-preserved-only-dup-voided",
        `invoice ${invoice.id} is missing in final state`,
      );
      continue;
    }
    const pair = pairOfMember.get(invoice.customer_id);
    if (!pair) continue; // unrelated rows are checked by unrelated-records-unchanged
    const edited = changedFields(invoice, f, ["customer_id", "status"]);
    if (edited.length > 0) {
      viol(
        "invoices-preserved-only-dup-voided",
        `invoice ${invoice.id} was edited (${edited.join(", ")})`,
      );
    }
    if (invoice.status === "void") {
      if (f.status !== "void" || f.customer_id !== invoice.customer_id) {
        viol(
          "invoices-preserved-only-dup-voided",
          `invoice ${invoice.id} was already void and must stay untouched on customer ${invoice.customer_id}`,
        );
      }
      continue;
    }
    if (pair.nonSurvivingDupIds.has(invoice.id)) {
      if (f.status !== "void") {
        viol(
          "invoices-preserved-only-dup-voided",
          `invoice ${invoice.id} (${invoice.number}) is a duplicated copy and should be void but is ${f.status}`,
        );
      }
      if (f.customer_id !== invoice.customer_id) {
        viol(
          "invoices-preserved-only-dup-voided",
          `invoice ${invoice.id} (${invoice.number}) is a duplicated copy and must stay on customer ${invoice.customer_id} (void is not transfer) but is on customer ${f.customer_id}`,
        );
      }
    } else {
      if (f.status !== invoice.status) {
        viol(
          "invoices-preserved-only-dup-voided",
          `invoice ${invoice.id} (${invoice.number}) should keep status ${invoice.status} but is ${f.status}`,
        );
      }
      if (f.customer_id !== pair.canonical.id) {
        viol(
          "invoices-preserved-only-dup-voided",
          `invoice ${invoice.id} (${invoice.number}) should sit on canonical customer ${pair.canonical.id} but is on customer ${f.customer_id}`,
        );
      }
    }
  }

  // duplicate-deactivated-not-deleted
  for (const pair of pairs) {
    for (const dup of pair.duplicates) {
      const f = finalCustomers.get(dup.id);
      if (!f) {
        viol(
          "duplicate-deactivated-not-deleted",
          `duplicate customer ${dup.id} is missing in final state`,
        );
        continue;
      }
      if (f.status !== "deactivated") {
        viol(
          "duplicate-deactivated-not-deleted",
          `duplicate customer ${dup.id} should be deactivated but is ${f.status}`,
        );
      }
      const edited = changedFields(dup, f, ["status"]);
      if (edited.length > 0) {
        viol(
          "duplicate-deactivated-not-deleted",
          `duplicate customer ${dup.id} was edited (${edited.join(", ")})`,
        );
      }
    }
  }

  // accurate-audit-event
  const initialEventIds = new Set(initial.audit_events.map((e) => e.id));
  const finalEvents = new Map(final.audit_events.map((e) => [e.id, e]));
  for (const event of initial.audit_events) {
    const f = finalEvents.get(event.id);
    if (!f) {
      viol(
        "accurate-audit-event",
        `pre-existing audit event ${event.id} is missing in final state`,
      );
      continue;
    }
    const edited = changedFields(event, f);
    if (edited.length > 0) {
      viol(
        "accurate-audit-event",
        `pre-existing audit event ${event.id} changed (${edited.join(", ")})`,
      );
    }
  }
  const newMergeEvents = final.audit_events.filter(
    (e) => !initialEventIds.has(e.id) && e.action === "customer.dedup.merge",
  );
  const expectedDups = pairs.flatMap((pair) => pair.duplicates.map((dup) => ({ pair, dup })));
  if (newMergeEvents.length !== expectedDups.length) {
    viol(
      "accurate-audit-event",
      `expected ${expectedDups.length} customer.dedup.merge audit event(s) but found ${newMergeEvents.length}`,
    );
  }
  for (const { pair, dup } of expectedDups) {
    const events = newMergeEvents.filter(
      (e) => e.entity_type === "customer" && e.entity_id === dup.id,
    );
    if (events.length === 0) {
      viol(
        "accurate-audit-event",
        `no customer.dedup.merge audit event for deactivated customer ${dup.id}`,
      );
      continue;
    }
    if (events.length > 1) {
      viol(
        "accurate-audit-event",
        `multiple customer.dedup.merge audit events for customer ${dup.id}`,
      );
      continue;
    }
    const event = events[0];
    // created_at stays unchecked: verify() receives no task clock, so the
    // expected value cannot be derived from state (known limitation).
    if (event.actor !== "intervention") {
      viol(
        "accurate-audit-event",
        `audit event ${event.id}: actor should be "intervention" but is ${JSON.stringify(event.actor)}`,
      );
    }
    let details: Record<string, unknown>;
    try {
      details = JSON.parse(event.details) as Record<string, unknown>;
    } catch {
      viol("accurate-audit-event", `audit event ${event.id} details are not valid JSON`);
      continue;
    }
    if (details.canonical_customer_id !== pair.canonical.id) {
      viol(
        "accurate-audit-event",
        `audit event ${event.id}: canonical_customer_id should be ${pair.canonical.id} but is ${JSON.stringify(details.canonical_customer_id)}`,
      );
    }
    if (details.deactivated_customer_id !== dup.id) {
      viol(
        "accurate-audit-event",
        `audit event ${event.id}: deactivated_customer_id should be ${dup.id} but is ${JSON.stringify(details.deactivated_customer_id)}`,
      );
    }
    const movedTickets = sortedIds(
      initial.tickets.filter(
        (t) => t.customer_id === dup.id && finalTickets.get(t.id)?.customer_id === pair.canonical.id,
      ),
    );
    const movedInvoices = sortedIds(
      initial.invoices.filter(
        (i) => i.customer_id === dup.id && finalInvoices.get(i.id)?.customer_id === pair.canonical.id,
      ),
    );
    const voidedInvoices = sortedIds(
      initial.invoices.filter(
        (i) =>
          i.customer_id === dup.id &&
          i.status !== "void" &&
          finalInvoices.get(i.id)?.status === "void",
      ),
    );
    const checkIdSet = (key: string, expected: number[]) => {
      const value = details[key];
      const actual =
        Array.isArray(value) && value.every((v) => typeof v === "number")
          ? [...value].sort((a, b) => a - b)
          : null;
      if (actual === null || JSON.stringify(actual) !== JSON.stringify(expected)) {
        viol(
          "accurate-audit-event",
          `audit event ${event.id}: ${key} should be ${JSON.stringify(expected)} but is ${JSON.stringify(value)}`,
          { expected, actual: value },
        );
      }
    };
    checkIdSet("transferred_ticket_ids", movedTickets);
    checkIdSet("transferred_invoice_ids", movedInvoices);
    checkIdSet("voided_invoice_ids", voidedInvoices);
    if (typeof details.reason !== "string" || details.reason.length === 0) {
      viol("accurate-audit-event", `audit event ${event.id}: reason should be a non-empty string`);
    }
  }
  const expectedDupIds = new Set(expectedDups.map(({ dup }) => dup.id));
  for (const event of newMergeEvents) {
    if (event.entity_type !== "customer" || !expectedDupIds.has(event.entity_id)) {
      viol(
        "accurate-audit-event",
        `unexpected customer.dedup.merge audit event ${event.id} for ${event.entity_type} ${event.entity_id}`,
      );
    }
  }
  for (const event of final.audit_events) {
    if (initialEventIds.has(event.id) || event.action === "customer.dedup.merge") continue;
    viol(
      "accurate-audit-event",
      `unexpected audit event ${event.id} with action ${JSON.stringify(event.action)}`,
    );
  }

  // unrelated-records-unchanged
  for (const customer of initial.customers) {
    if (pairOfMember.has(customer.id)) continue;
    const f = finalCustomers.get(customer.id);
    if (!f) {
      viol(
        "unrelated-records-unchanged",
        `unrelated customer ${customer.id} is missing in final state`,
      );
      continue;
    }
    const edited = changedFields(customer, f);
    if (edited.length > 0) {
      viol(
        "unrelated-records-unchanged",
        `unrelated customer ${customer.id} changed (${edited.join(", ")})`,
      );
    }
  }
  for (const ticket of initial.tickets) {
    if (pairOfMember.has(ticket.customer_id)) continue;
    const f = finalTickets.get(ticket.id);
    if (!f) {
      viol("unrelated-records-unchanged", `unrelated ticket ${ticket.id} is missing in final state`);
      continue;
    }
    const edited = changedFields(ticket, f);
    if (edited.length > 0) {
      viol(
        "unrelated-records-unchanged",
        `unrelated ticket ${ticket.id} changed (${edited.join(", ")})`,
      );
    }
  }
  for (const invoice of initial.invoices) {
    if (pairOfMember.has(invoice.customer_id)) continue;
    const f = finalInvoices.get(invoice.id);
    if (!f) {
      viol(
        "unrelated-records-unchanged",
        `unrelated invoice ${invoice.id} is missing in final state`,
      );
      continue;
    }
    const edited = changedFields(invoice, f);
    if (edited.length > 0) {
      viol(
        "unrelated-records-unchanged",
        `unrelated invoice ${invoice.id} changed (${edited.join(", ")})`,
      );
    }
  }

  // no-rows-deleted
  const checkTable = (
    table: string,
    initialRows: { id: number }[],
    finalRows: { id: number }[],
    allowGrowth: boolean,
  ) => {
    const finalIds = new Set(finalRows.map((r) => r.id));
    const missing = initialRows.filter((r) => !finalIds.has(r.id)).map((r) => r.id);
    if (missing.length > 0) {
      viol("no-rows-deleted", `${table}: ${missing.length} row(s) deleted (ids ${missing.join(", ")})`);
    }
    if (!allowGrowth) {
      const initialIds = new Set(initialRows.map((r) => r.id));
      const added = finalRows.filter((r) => !initialIds.has(r.id)).map((r) => r.id);
      if (added.length > 0) {
        viol("no-rows-deleted", `${table}: unexpected new rows (ids ${added.join(", ")})`);
      }
    }
  };
  checkTable("customers", initial.customers, final.customers, false);
  checkTable("tickets", initial.tickets, final.tickets, false);
  checkTable("invoices", initial.invoices, final.invoices, false);
  checkTable("audit_events", initial.audit_events, final.audit_events, true);

  return violations;
}
