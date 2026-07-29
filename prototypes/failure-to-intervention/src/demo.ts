import { loadCases } from "./cases";
import { naiveIntervention } from "./interventions/naive";
import { robustIntervention } from "./interventions/robust";
import { runEvaluation } from "./report";
import type { EvaluationReport } from "./schemas";

const interventions = [
  { name: "naive", fn: naiveIntervention },
  { name: "robust", fn: robustIntervention },
];

const reports: EvaluationReport[] = [];

const header =
  "case".padEnd(24) + interventions.map((i) => i.name.padEnd(8)).join("").trimEnd();
console.log(header);

for (const caseFile of loadCases()) {
  let row = caseFile.trace.case_id.padEnd(24);
  interventions.forEach((intervention, index) => {
    const report = runEvaluation(caseFile, intervention.name, intervention.fn);
    reports.push(report);
    const cell = report.passed ? "PASS" : "FAIL";
    row += index === interventions.length - 1 ? cell : cell.padEnd(8);
  });
  console.log(row);
}

const failures = reports.filter((r) => !r.passed);
if (failures.length > 0) {
  console.log("");
  console.log("violations:");
  for (const report of failures) {
    for (const v of report.violations) {
      console.log(`- ${report.case_id} x ${report.intervention} | ${v.invariant}: ${v.message}`);
    }
  }
}

console.log("");
console.log(
  "legend: naive is the overfit shortcut — expected to PASS original-incident and FAIL every counterfactual; robust is expected to PASS all four.",
);
