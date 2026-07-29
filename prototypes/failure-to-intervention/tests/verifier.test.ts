import { describe, expect, it } from "vitest";
import { reconstruct, snapshot, type Database, type Snapshot } from "../src/db";
import { loadCases, type CaseFile } from "../src/cases";
import { defineTask } from "../src/task";
import { createDomainApi, type DomainApi } from "../src/domain-api";
import { verify, type InvariantViolation } from "../src/verifier";
import { runEvaluation } from "../src/report";
import { robustIntervention } from "../src/interventions/robust";

const cases = loadCases();
const byId = new Map(cases.map((cf) => [cf.trace.case_id, cf]));

function getCase(id: string): CaseFile {
  const cf = byId.get(id);
  if (!cf) throw new Error(`case ${id} not found in loadCases()`);
  return cf;
}

const REASON = "duplicate customer merge";

// Replays a correct merge of the original incident's pair (customer 2 into
// canonical customer 1) EXCEPT the audit event, so each known-fail test adds
// exactly one defect on top of an otherwise-clean final state.
function buildMergedFinal(
  tweak?: (api: DomainApi, db: Database) => void,
): { initial: Snapshot; final: Snapshot } {
  const cf = getCase("original-incident");
  const task = defineTask(cf.trace);
  const db = reconstruct(cf.trace.seed);
  const initial = snapshot(db);
  const api = createDomainApi(db, () => task.issued_at);
  api.voidInvoice(2, REASON);
  api.transferTicket(1, 1);
  api.deactivateCustomer(2, REASON);
  tweak?.(api, db);
  const final = snapshot(db);
  db.close();
  return { initial, final };
}

function writeCorrectMergeAudit(api: DomainApi, details: Record<string, unknown> = {}): void {
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
      ...details,
    },
  });
}

function invariantIds(violations: InvariantViolation[]): string[] {
  return [...new Set(violations.map((v) => v.invariant))].sort();
}

describe("known-pass", () => {
  it("robustIntervention via runEvaluation passes every case with zero violations", () => {
    for (const cf of cases) {
      const report = runEvaluation(cf, "robust", robustIntervention);
      expect(report.passed, `${cf.trace.case_id}: ${JSON.stringify(report.violations)}`).toBe(true);
      expect(report.violations).toEqual([]);
    }
  });

  it("the hand-built merge used by the known-fail tests is itself clean under verify()", () => {
    const { initial, final } = buildMergedFinal((api) => writeCorrectMergeAudit(api));
    expect(verify(initial, final)).toEqual([]);
  });
});

describe("known-fail: each broken behavior trips its named invariant(s)", () => {
  it("a. duplicate customer row deleted outright -> no-rows-deleted AND duplicate-deactivated-not-deleted", () => {
    const { initial, final } = buildMergedFinal((api, db) => {
      writeCorrectMergeAudit(api);
      // better-sqlite3 enforces foreign keys by default; the cheat has to lift
      // that first because voided invoice 2 still references the deleted row.
      db.pragma("foreign_keys = OFF");
      db.prepare("DELETE FROM customers WHERE id = 2").run();
    });
    const violations = verify(initial, final);
    expect(invariantIds(violations)).toEqual([
      "duplicate-deactivated-not-deleted",
      "no-rows-deleted",
    ]);
  });

  it("b. a legitimate (non-duplicated) invoice voided -> invoices-preserved-only-dup-voided", () => {
    const { initial, final } = buildMergedFinal((api) => {
      writeCorrectMergeAudit(api);
      api.voidInvoice(3, "wrongly voided a legitimate paid invoice");
    });
    const violations = verify(initial, final);
    expect(invariantIds(violations)).toEqual(["invoices-preserved-only-dup-voided"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("invoice 3 (INV-4000)");
  });

  it("c. no audit event written -> accurate-audit-event", () => {
    const { initial, final } = buildMergedFinal();
    const violations = verify(initial, final);
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
  });

  it("d. unrelated customer's row edited (Grace Lee's email changed) -> unrelated-records-unchanged", () => {
    const { initial, final } = buildMergedFinal((api, db) => {
      writeCorrectMergeAudit(api);
      db.prepare("UPDATE customers SET email = ? WHERE id = 3").run("grace.lee@example.com");
    });
    const violations = verify(initial, final);
    expect(invariantIds(violations)).toEqual(["unrelated-records-unchanged"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("customer 3");
  });

  it("e. wrong canonical kept: earliest-created deactivated, newer kept active -> single-active-canonical", () => {
    const { initial, final } = buildMergedFinal((api, db) => {
      writeCorrectMergeAudit(api);
      api.deactivateCustomer(1, "kept the newer record instead");
      db.prepare("UPDATE customers SET status = 'active' WHERE id = 2").run();
    });
    const violations = verify(initial, final);
    // A still-active duplicate necessarily also trips duplicate-deactivated-not-deleted.
    expect(invariantIds(violations)).toEqual([
      "duplicate-deactivated-not-deleted",
      "single-active-canonical",
    ]);
  });

  it("f. audit event with wrong canonical_customer_id in details -> accurate-audit-event", () => {
    const { initial, final } = buildMergedFinal((api) => {
      writeCorrectMergeAudit(api, { canonical_customer_id: 2 });
    });
    const violations = verify(initial, final);
    expect(invariantIds(violations)).toEqual(["accurate-audit-event"]);
    expect(violations).toHaveLength(1);
    expect(violations[0].message).toContain("canonical_customer_id");
  });
});

describe("verifier derives its expectations from the initial state", () => {
  it("verify(initial, initial) on the untouched original incident is NOT clean", () => {
    const cf = getCase("original-incident");
    const db = reconstruct(cf.trace.seed);
    const initial = snapshot(db);
    db.close();
    const violations = verify(initial, initial);
    expect(invariantIds(violations)).toEqual([
      "accurate-audit-event",
      "duplicate-deactivated-not-deleted",
      "invoices-preserved-only-dup-voided",
      "single-active-canonical",
      "tickets-preserved-attached",
    ]);
  });

  it("verify(initial, initial) flags every untouched case, so a do-nothing run always fails", () => {
    for (const cf of cases) {
      const db = reconstruct(cf.trace.seed);
      const initial = snapshot(db);
      db.close();
      const ids = invariantIds(verify(initial, initial));
      expect(ids, cf.trace.case_id).toContain("single-active-canonical");
      expect(ids, cf.trace.case_id).toContain("accurate-audit-event");
    }
  });
});
