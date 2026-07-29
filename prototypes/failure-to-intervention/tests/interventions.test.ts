import { describe, expect, it } from "vitest";
import { loadCases, type CaseFile } from "../src/cases";
import { defineTask } from "../src/task";
import { runEvaluation, type Intervention } from "../src/report";
import { naiveIntervention } from "../src/interventions/naive";
import { robustIntervention } from "../src/interventions/robust";
import { ReportSchema, type EvaluationReport } from "../src/schemas";

const cases = loadCases();
const byId = new Map(cases.map((cf) => [cf.trace.case_id, cf]));

function getCase(id: string): CaseFile {
  const cf = byId.get(id);
  if (!cf) throw new Error(`case ${id} not found in loadCases()`);
  return cf;
}

const interventions: [string, Intervention][] = [
  ["naive", naiveIntervention],
  ["robust", robustIntervention],
];

function invariantIds(report: EvaluationReport): string[] {
  return [...new Set(report.violations.map((v) => v.invariant))];
}

function runAll(): EvaluationReport[] {
  return cases.flatMap((cf) => interventions.map(([name, fn]) => runEvaluation(cf, name, fn)));
}

describe("naiveIntervention (the overfit shortcut)", () => {
  it("passes original-incident with zero violations", () => {
    const report = runEvaluation(getCase("original-incident"), "naive", naiveIntervention);
    expect(report.passed, JSON.stringify(report.violations)).toBe(true);
    expect(report.violations).toEqual([]);
  });

  it.each([
    ["reordered-ids", "single-active-canonical"],
    ["dup-owns-legitimate", "invoices-preserved-only-dup-voided"],
    ["unrelated-lookalike", "unrelated-records-unchanged"],
  ])("fails %s, tripping %s", (caseId, invariant) => {
    const report = runEvaluation(getCase(caseId), "naive", naiveIntervention);
    expect(report.passed).toBe(false);
    expect(invariantIds(report)).toContain(invariant);
  });
});

describe("robustIntervention", () => {
  it("passes all four cases", () => {
    for (const cf of cases) {
      const report = runEvaluation(cf, "robust", robustIntervention);
      expect(report.passed, `${cf.trace.case_id}: ${JSON.stringify(report.violations)}`).toBe(true);
      expect(report.violations).toEqual([]);
    }
  });
});

describe("full evaluation matrix", () => {
  it("matches the pinned PASS/FAIL matrix for every case x intervention", () => {
    const matrix: Record<string, Record<string, boolean>> = {};
    for (const cf of cases) {
      matrix[cf.trace.case_id] = {};
      for (const [name, fn] of interventions) {
        matrix[cf.trace.case_id][name] = runEvaluation(cf, name, fn).passed;
      }
    }
    expect(matrix).toEqual({
      "original-incident": { naive: true, robust: true },
      "dup-owns-legitimate": { naive: false, robust: true },
      "reordered-ids": { naive: false, robust: true },
      "unrelated-lookalike": { naive: false, robust: true },
    });
  });
});

describe("evaluation reports", () => {
  it("every EvaluationReport passes ReportSchema.parse", () => {
    for (const report of runAll()) {
      expect(() => ReportSchema.parse(report)).not.toThrow();
    }
  });

  it("initial_digest is identical across interventions of the same case (reconstruction is intervention-independent)", () => {
    for (const cf of cases) {
      const digests = interventions.map(([name, fn]) => runEvaluation(cf, name, fn).initial_digest);
      expect(new Set(digests).size, cf.trace.case_id).toBe(1);
      expect(digests[0]).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it("checked_at is the task's issued_at, keeping reports deterministic", () => {
    for (const report of runAll()) {
      const cf = getCase(report.case_id);
      expect(report.checked_at).toBe(defineTask(cf.trace).issued_at);
    }
  });
});
