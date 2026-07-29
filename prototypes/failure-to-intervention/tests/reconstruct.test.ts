import { describe, expect, it } from "vitest";
import { digest, reconstruct, snapshot } from "../src/db";
import { loadCases } from "../src/cases";
import { SeedSchema } from "../src/schemas";
import { createDomainApi } from "../src/domain-api";

const cases = loadCases();
const original = cases[0];

const initialDigestOf = (seed: (typeof original)["trace"]["seed"]) =>
  digest(snapshot(reconstruct(seed)));

describe("reconstruct + digest", () => {
  it("reconstructing the same seed twice yields identical snapshots and identical sha256 digests", () => {
    const dbA = reconstruct(original.trace.seed);
    const snapA = snapshot(dbA);
    dbA.close();
    const dbB = reconstruct(original.trace.seed);
    const snapB = snapshot(dbB);
    dbB.close();

    expect(snapA).toEqual(snapB);

    const digestA = digest(snapA);
    expect(digestA).toMatch(/^[0-9a-f]{64}$/);
    expect(digestA).toBe(digest(snapB));
  });

  it("loadCases returns the original incident first, then counterfactuals sorted by filename", () => {
    expect(cases.map((cf) => cf.trace.case_id)).toEqual([
      "original-incident",
      "dup-owns-legitimate",
      "reordered-ids",
      "unrelated-lookalike",
    ]);
  });

  it("all four cases reconstruct into Zod-valid state", () => {
    expect(cases).toHaveLength(4);
    for (const cf of cases) {
      const db = reconstruct(cf.trace.seed);
      const snap = snapshot(db);
      db.close();
      expect(() => SeedSchema.parse(snap)).not.toThrow();
    }
  });

  it("different cases produce different initial digests", () => {
    const digests = cases.map((cf) => initialDigestOf(cf.trace.seed));
    expect(new Set(digests).size).toBe(cases.length);
  });

  it("reset works: mutating one reconstruction leaves a fresh reconstruction pristine", () => {
    const pristine = initialDigestOf(original.trace.seed);

    const db = reconstruct(original.trace.seed);
    const api = createDomainApi(db, () => original.trace.task.issued_at);
    api.voidInvoice(2, "mutating the environment");
    api.deactivateCustomer(2, "mutating the environment");
    const mutated = digest(snapshot(db));
    db.close();
    expect(mutated).not.toBe(pristine);

    expect(initialDigestOf(original.trace.seed)).toBe(pristine);
  });
});
