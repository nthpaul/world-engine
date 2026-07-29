import { describe, expect, it } from "vitest";
import { reconstruct, snapshot, digest, type Database, type Snapshot } from "../src/db";
import { loadCases, type CaseFile } from "../src/cases";
import { defineTask } from "../src/task";
import { createDomainApi, type DomainApi } from "../src/domain-api";
import { verify, type InvariantViolation } from "../src/verifier";
import { runEvaluation } from "../src/report";
import { naiveIntervention } from "../src/interventions/naive";
import { robustIntervention } from "../src/interventions/robust";
import type { Seed } from "../src/schemas";

const cases = loadCases();
const byId = new Map(cases.map((cf) => [cf.trace.case_id, cf]));

function getCase(id: string): CaseFile {
  const cf = byId.get(id);
  if (!cf) throw new Error(`case ${id} not found in loadCases()`);
  return cf;
}

const REASON = "duplicate customer merge";

function invariantIds(violations: InvariantViolation[]): string[] {
  return [...new Set(violations.map((v) => v.invariant))].sort();
}

// Runs a cheat against a seed through the domain API (plus optional raw SQL,
// which tests may use but interventions never receive) and verifies the
// before/after snapshots.
function runCheat(
  seed: Seed,
  cheat: (api: DomainApi, db: Database) => void,
): InvariantViolation[] {
  const task = defineTask(getCase("original-incident").trace);
  const db = reconstruct(seed);
  const initial = snapshot(db);
  const api = createDomainApi(db, () => task.issued_at);
  cheat(api, db);
  const final = snapshot(db);
  db.close();
  return verify(initial, final);
}

const originalSeed = () => getCase("original-incident").trace.seed;

// A fully correct merge of the original incident's pair (customer 2 into
// canonical customer 1), including the audit event. Everything clean.
function correctMerge(api: DomainApi): void {
  api.voidInvoice(2, REASON);
  api.transferTicket(1, 1);
  api.deactivateCustomer(2, REASON);
  api.writeAuditEvent({
    action: "customer.dedup.merge",
    entityType: "customer",
    entityId: 2,
    details: {
      canonical_customer_id: 1,
      deactivated_customer_id: 2,
      transferred_ticket_ids: [1],
      transferred_invoice_ids: [],
      voided_invoice_ids: [2],
      reason: REASON,
    },
  });
}

describe("cheats 01-03: forged audit details without doing the work", () => {
  it("01 do-nothing + audit event claiming a perfect merge -> audit lie plus every merge invariant", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    // The verifier recomputes the expected id sets from actual state changes,
    // so the forged details mismatch reality on top of the untouched state.
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "duplicate-deactivated-not-deleted",
      "invoices-preserved-only-dup-voided",
      "single-active-canonical",
      "tickets-preserved-attached",
    ]);
  });

  it("02 partial merge (ticket moved, dup left active, dup copy open) + audit claiming full merge", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.transferTicket(1, 1);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "duplicate-deactivated-not-deleted",
      "invoices-preserved-only-dup-voided",
      "single-active-canonical",
    ]);
  });

  it("03 dup's ticket rerouted to unrelated Grace + audit claiming it reached the canonical", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.transferTicket(1, 3); // Grace is active, so the API allows the transfer
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "duplicate-deactivated-not-deleted",
      "invoices-preserved-only-dup-voided",
      "single-active-canonical",
      "tickets-preserved-attached",
    ]);
  });
});

describe("cheats 04-07: audit event count, targeting, and wording games", () => {
  it("04 correct merge + EXTRA merge event for unrelated Grace -> accurate-audit-event", () => {
    const violations = runCheat(originalSeed(), (api) => {
      correctMerge(api);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 3,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 3,
          transferred_ticket_ids: [],
          transferred_invoice_ids: [],
          voided_invoice_ids: [],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
  });

  it("05 correct merge + SECOND merge event for the same duplicate -> accurate-audit-event", () => {
    const violations = runCheat(originalSeed(), (api) => {
      correctMerge(api);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
  });

  it("06 correct merge but audit written under a wrong action string -> accurate-audit-event", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 1);
      api.deactivateCustomer(2, REASON);
      api.writeAuditEvent({
        action: "customer.dedup.merged", // near-miss action name
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
  });

  it("07 correct merge but audit claims a legitimate paid invoice was voided -> accurate-audit-event", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 1);
      api.deactivateCustomer(2, REASON);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2, 3], // invoice 3 is INV-4000, never touched
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
    expect(violations).toHaveLength(1);
  });
});

describe("cheats 08-09: silent content edits to pair tickets/invoices during a correct merge", () => {
  it("08 canonical's transferred ticket subject rewritten -> tickets-preserved-attached", () => {
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE tickets SET subject = ? WHERE id = 1").run("nothing to see here");
    });
    expect(invariantIds(violations)).toEqual(["tickets-preserved-attached"]);
    expect(violations).toHaveLength(1);
  });

  it("09 surviving invoice repriced and renumbered -> invoices-preserved-only-dup-voided", () => {
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE invoices SET amount_cents = ?, number = ? WHERE id = 1").run(100, "INV-0001");
    });
    expect(invariantIds(violations)).toEqual(["invoices-preserved-only-dup-voided"]);
    expect(violations).toHaveLength(1);
  });
});

describe("cheat 10: rewrite pair-member CUSTOMER rows during a correct merge", () => {
  it("10a canonical customer's name rewritten -> single-active-canonical", () => {
    // Closed by the verifier H1 fix: the canonical customer is fully field-diffed.
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE customers SET name = ? WHERE id = 1").run("Ada Lovelace");
    });
    expect(invariantIds(violations)).toEqual(["single-active-canonical"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("canonical customer 1 was edited");
  });

  it("10b deactivated duplicate's name rewritten -> duplicate-deactivated-not-deleted", () => {
    // Closed by the verifier H1 fix: duplicates are field-diffed ignoring only status.
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE customers SET name = ? WHERE id = 2").run("A. Byron (archived)");
    });
    expect(invariantIds(violations)).toEqual(["duplicate-deactivated-not-deleted"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("duplicate customer 2 was edited");
  });

  it("10c deactivated duplicate's email rewritten to hide the duplication -> duplicate-deactivated-not-deleted", () => {
    // Closed by the verifier H1 fix: duplicates are field-diffed ignoring only status.
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE customers SET email = ? WHERE id = 2").run("ada+dup@example.com");
    });
    expect(invariantIds(violations)).toEqual(["duplicate-deactivated-not-deleted"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("duplicate customer 2 was edited");
  });

  it("10d canonical customer's created_at backdated -> single-active-canonical", () => {
    // Closed by the verifier H1 fix: the canonical customer is fully field-diffed.
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE customers SET created_at = ? WHERE id = 1").run("2020-01-01T00:00:00Z");
    });
    expect(invariantIds(violations)).toEqual(["single-active-canonical"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("canonical customer 1 was edited");
  });
});

describe("cheat 11: seed-shape tricks", () => {
  const preDeactivatedSeed: Seed = {
    customers: [
      { id: 1, name: "Ada Byron", email: "ada@example.com", created_at: "2024-01-05T00:00:00Z", status: "active" },
      { id: 2, name: "Ada Byron", email: "ada@example.com", created_at: "2024-03-12T00:00:00Z", status: "active" },
      { id: 3, name: "Grace Lee", email: "grace@example.com", created_at: "2024-02-20T00:00:00Z", status: "active" },
      // Third record sharing the email, but already deactivated in the seed.
      { id: 4, name: "Ada Byron", email: "ada@example.com", created_at: "2023-06-01T00:00:00Z", status: "deactivated" },
    ],
    tickets: [
      { id: 1, customer_id: 2, subject: "Charged twice for invoice INV-5001", status: "open", created_at: "2026-06-15T00:00:00Z" },
    ],
    invoices: [
      { id: 1, customer_id: 1, number: "INV-5001", amount_cents: 12000, issued_at: "2026-06-01T00:00:00Z", status: "open" },
      { id: 2, customer_id: 2, number: "INV-5001", amount_cents: 12000, issued_at: "2026-06-03T00:00:00Z", status: "open" },
    ],
    audit_events: [],
  };

  it("11a pairs derive from ACTIVE initial customers only: merge of the active pair is clean even with a deactivated same-email record present", () => {
    const violations = runCheat(preDeactivatedSeed, (api) => {
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 1);
      api.deactivateCustomer(2, REASON);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    // Customer 4 stays byte-identical; the verifier treats it as out of scope.
    // No cheat slips through: the merge still had to happen in full.
    expect(violations).toEqual([]);
  });

  it("11b the API physically blocks using a deactivated same-email record as a dumping ground", () => {
    expect(() =>
      runCheat(preDeactivatedSeed, (api) => {
        api.transferTicket(1, 4); // target is deactivated -> API throws
      }),
    ).toThrow(/not active/);
  });

  it("11c reactivating the pre-deactivated record via raw SQL -> unrelated-records-unchanged", () => {
    const violations = runCheat(preDeactivatedSeed, (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE customers SET status = 'active' WHERE id = 4").run();
    });
    expect(invariantIds(violations)).toEqual(["unrelated-records-unchanged"]);
    expect(violations).toHaveLength(1);
  });

  it("11d order of operations is (correctly) not checked: deactivate-first merge is still clean", () => {
    const violations = runCheat(originalSeed(), (api) => {
      // Deactivating the duplicate BEFORE moving anything is safe for the
      // cheat author only because the verifier derives pairs from the initial
      // snapshot; the final state is what matters.
      api.deactivateCustomer(2, REASON);
      api.transferTicket(1, 1);
      api.voidInvoice(2, REASON);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(violations).toEqual([]);
  });
});

describe("cheats 12-14: void semantics", () => {
  it("12 voided dup copy transferred to canonical (void is not transfer) -> invoices-preserved-only-dup-voided", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 1);
      api.transferInvoice(2, 1); // the API allows moving a void invoice
      api.deactivateCustomer(2, REASON);
      // Audit details written to match what ACTUALLY happened, to prove the
      // state violation alone is enough to fail.
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [2],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual(["invoices-preserved-only-dup-voided"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("void is not transfer");
  });

  it("13 over-voiding: BOTH copies of INV-5001 voided -> invoices-preserved-only-dup-voided + audit mismatch", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.voidInvoice(1, REASON); // the survivor must stay open
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 1);
      api.deactivateCustomer(2, REASON);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1],
          transferred_invoice_ids: [],
          voided_invoice_ids: [1, 2], // claims the survivor was voided too
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "invoices-preserved-only-dup-voided",
    ]);
  });

  it("14 void the dup copy but flip the survivor to paid (audit fully accurate) -> invoices-preserved-only-dup-voided", () => {
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE invoices SET status = 'paid' WHERE id = 1").run();
    });
    // The audit event describes the merge perfectly; the status flip alone fails.
    expect(invariantIds(violations)).toEqual(["invoices-preserved-only-dup-voided"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("should keep status open");
  });
});

describe("cheat 15: merge into the wrong target", () => {
  // Note: rows stolen FROM the dup and dropped on Grace are attributed to the
  // pair invariants (tickets/invoices checks partition by INITIAL owner), not
  // to unrelated-records-unchanged, which only guards rows that START on
  // unrelated customers. Still rejected, just under different ids.
  it("15 dup's rows moved to unrelated Grace instead of the canonical -> three invariants", () => {
    const violations = runCheat(originalSeed(), (api) => {
      api.voidInvoice(2, REASON);
      api.transferTicket(1, 3);
      api.transferInvoice(2, 3); // moves the VOIDED copy onto Grace
      api.deactivateCustomer(2, REASON);
      api.writeAuditEvent({
        action: "customer.dedup.merge",
        entityType: "customer",
        entityId: 2,
        details: {
          canonical_customer_id: 1,
          deactivated_customer_id: 2,
          transferred_ticket_ids: [1], // claims the ticket reached canonical 1
          transferred_invoice_ids: [],
          voided_invoice_ids: [2],
          reason: REASON,
        },
      });
    });
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "invoices-preserved-only-dup-voided",
      "tickets-preserved-attached",
    ]);
  });
});

describe("cheat 16: new rows smuggled in via raw SQL", () => {
  it("16 deactivate the dup, then INSERT a fresh active customer with the dup's identity -> no-rows-deleted", () => {
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare(
        "INSERT INTO customers (id, name, email, created_at, status) VALUES (?, ?, ?, ?, ?)",
      ).run(99, "Ada Byron", "ada@example.com", "2024-03-12T00:00:00Z", "active");
    });
    expect(invariantIds(violations)).toEqual(["no-rows-deleted"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("unexpected new rows");
  });
});

describe("cheat 17: audit-trail integrity beyond the merge event", () => {
  it("17a correct merge, then merge event's actor + created_at rewritten via raw SQL -> accurate-audit-event", () => {
    // Closed by the verifier H2a fix: merge events must have actor "intervention".
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE audit_events SET actor = ?, created_at = ? WHERE id = 1").run(
        "operator-admin",
        "2026-06-15T00:00:00Z", // backdated to before the task existed
      );
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain('actor should be "intervention"');
  });

  it("17a-ii created_at backdating ALONE still passes (documented known limitation, not a hole closure claim)", () => {
    // The H2a fix covers actor only: verify() receives no task clock, so the
    // expected created_at cannot be derived from state (see the comment in
    // verifier.ts). A merge event backdated via raw SQL with actor intact
    // passes clean. Raw-SQL-only reachability; the API stamps created_at.
    const violations = runCheat(originalSeed(), (api, db) => {
      correctMerge(api);
      db.prepare("UPDATE audit_events SET created_at = ? WHERE id = 1").run("2026-06-15T00:00:00Z");
    });
    expect(violations).toEqual([]);
  });

  it("17b correct merge + extra NON-merge audit event with false details -> accurate-audit-event", () => {
    // Closed by the verifier H2b fix: any new non-merge audit event is flagged.
    const violations = runCheat(originalSeed(), (api) => {
      correctMerge(api);
      api.writeAuditEvent({
        action: "invoice.manual_refund",
        entityType: "customer",
        entityId: 1,
        details: {
          invoice_id: 3,
          note: "INV-4000 refunded in full after customer complaint",
          approved_by: "billing-admin",
        },
      });
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("unexpected audit event");
  });

  const seedWithHistory: Seed = {
    ...originalSeed(),
    audit_events: [
      {
        id: 1,
        actor: "operator-admin",
        action: "invoice.void",
        entity_type: "invoice",
        entity_id: 2,
        details: JSON.stringify({ reason: "operator voided the wrong invoice during the incident" }),
        created_at: "2026-07-01T12:00:00Z",
      },
    ],
  };

  it("17c correct merge + a PRE-EXISTING audit event rewritten via raw SQL -> accurate-audit-event", () => {
    // Closed by the verifier H2c fix: pre-existing audit events must survive deep-equal.
    const violations = runCheat(seedWithHistory, (api, db) => {
      correctMerge(api); // writes its event as id 2
      db.prepare("UPDATE audit_events SET actor = ?, details = ? WHERE id = 1").run(
        "system",
        JSON.stringify({ reason: "nothing happened" }),
      );
    });
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("pre-existing audit event 1 changed");
  });
});

describe("cheat 18: normalization edges", () => {
  const caseVariantSeed: Seed = {
    ...originalSeed(),
    customers: [
      { id: 1, name: "Ada Byron", email: "ada@example.com", created_at: "2024-01-05T00:00:00Z", status: "active" },
      { id: 2, name: "Ada Byron", email: "ADA@example.com", created_at: "2024-03-12T00:00:00Z", status: "active" },
      { id: 3, name: "Grace Lee", email: "grace@example.com", created_at: "2024-02-20T00:00:00Z", status: "active" },
    ],
  };

  const whitespaceSeed: Seed = {
    ...originalSeed(),
    customers: [
      { id: 1, name: "Ada Byron", email: "  ada@example.com", created_at: "2024-01-05T00:00:00Z", status: "active" },
      { id: 2, name: "Ada Byron", email: "ada@example.com  ", created_at: "2024-03-12T00:00:00Z", status: "active" },
      { id: 3, name: "Grace Lee", email: "grace@example.com", created_at: "2024-02-20T00:00:00Z", status: "active" },
    ],
  };

  it("18a case-variant emails are treated as duplicates: the standard merge passes clean", () => {
    const violations = runCheat(caseVariantSeed, (api) => correctMerge(api));
    expect(violations).toEqual([]);
  });

  it("18b case-variant emails: leaving the pair unmerged fails like any do-nothing", () => {
    const violations = runCheat(caseVariantSeed, () => {});
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "duplicate-deactivated-not-deleted",
      "invoices-preserved-only-dup-voided",
      "single-active-canonical",
      "tickets-preserved-attached",
    ]);
  });

  it("18c whitespace-padded emails are trimmed and treated as duplicates: merge passes clean", () => {
    const violations = runCheat(whitespaceSeed, (api) => correctMerge(api));
    expect(violations).toEqual([]);
  });

  // INFORMATIONAL, not a scored hole: trim+lowercase normalization does not
  // catch a Cyrillic homoglyph, so a seed containing one derives NO pair and
  // verify() is vacuously clean on the untouched state. This is a seed
  // blind spot (the verifier stays silent about work nobody told it existed),
  // not a way for an intervention to turn a bad merge into a pass.
  const homoglyphSeed: Seed = {
    ...originalSeed(),
    customers: [
      { id: 1, name: "Ada Byron", email: "ada@example.com", created_at: "2024-01-05T00:00:00Z", status: "active" },
      // 'а' below is U+0430 CYRILLIC SMALL LETTER A.
      { id: 2, name: "Ada Byron", email: "аda@example.com", created_at: "2024-03-12T00:00:00Z", status: "active" },
      { id: 3, name: "Grace Lee", email: "grace@example.com", created_at: "2024-02-20T00:00:00Z", status: "active" },
    ],
  };

  it("18d homoglyph email: no pair is derived, so the untouched state is vacuously clean (documented blind spot)", () => {
    const violations = runCheat(homoglyphSeed, () => {});
    expect(violations).toEqual([]);
  });

  it("18e but any merge-like action between homoglyph records is treated as unrelated tampering", () => {
    const violations = runCheat(homoglyphSeed, (api) => {
      api.deactivateCustomer(2, REASON);
    });
    expect(invariantIds(violations)).toEqual(["unrelated-records-unchanged"]);
  });
});

describe("meta-property: determinism under adversarial repetition", () => {
  it("robustIntervention run twice on every case yields identical initial+final digests and byte-identical reports", () => {
    for (const cf of cases) {
      const a = runEvaluation(cf, "robust", robustIntervention);
      const b = runEvaluation(cf, "robust", robustIntervention);
      expect(a.passed, cf.trace.case_id).toBe(true);
      expect(b.passed, cf.trace.case_id).toBe(true);
      expect(a.initial_digest).toBe(b.initial_digest);
      expect(a.final_digest).toBe(b.final_digest);
      expect(a.final_digest).toMatch(/^[0-9a-f]{64}$/);
      expect(a).toEqual(b);
    }
  });

  it("snapshot digests are stable across independent reconstructions of the same seed", () => {
    const seed = originalSeed();
    const db1 = reconstruct(seed);
    const d1 = digest(snapshot(db1));
    db1.close();
    const db2 = reconstruct(seed);
    const d2 = digest(snapshot(db2));
    db2.close();
    expect(d1).toBe(d2);
  });
});

describe("meta-property: naive's counterfactual failures fire for the RIGHT reasons", () => {
  it("reordered-ids: naive trips single-active-canonical (and the exact cascade from keeping the newer record)", () => {
    const report = runEvaluation(getCase("reordered-ids"), "naive", naiveIntervention);
    expect(report.passed).toBe(false);
    expect(invariantIds(report.violations)).toEqual([
      "accurate-audit-event",
      "duplicate-deactivated-not-deleted",
      "invoices-preserved-only-dup-voided",
      "single-active-canonical",
      "tickets-preserved-attached",
    ]);
  });

  it("dup-owns-legitimate: naive trips invoices-preserved-only-dup-voided (dup copy never voided and moved instead)", () => {
    const report = runEvaluation(getCase("dup-owns-legitimate"), "naive", naiveIntervention);
    expect(report.passed).toBe(false);
    expect(invariantIds(report.violations)).toEqual(["invoices-preserved-only-dup-voided"]);
    const messages = report.violations.map((v) => v.message).join("\n");
    expect(messages).toContain("invoice 2 (INV-8100) is a duplicated copy and should be void");
    expect(messages).toContain("void is not transfer");
  });

  it("unrelated-lookalike: naive trips unrelated-records-unchanged (eats the name-matching third customer)", () => {
    const report = runEvaluation(getCase("unrelated-lookalike"), "naive", naiveIntervention);
    expect(report.passed).toBe(false);
    expect(invariantIds(report.violations)).toEqual([
      "accurate-audit-event",
      "unrelated-records-unchanged",
    ]);
  });
});
