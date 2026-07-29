import { reconstruct, snapshot, digest } from "./db";
import { defineTask } from "./task";
import { createDomainApi, type Intervention } from "./domain-api";
import { verify, type InvariantViolation } from "./verifier";
import { ReportSchema, type EvaluationReport } from "./schemas";
import type { CaseFile } from "./cases";

export type { Intervention } from "./domain-api";

export function runEvaluation(cf: CaseFile, name: string, fn: Intervention): EvaluationReport {
  const db = reconstruct(cf.trace.seed);
  const initial = snapshot(db);
  const initialDigest = digest(initial);
  const task = defineTask(cf.trace);
  const api = createDomainApi(db, () => task.issued_at);

  const thrown: InvariantViolation[] = [];
  try {
    fn(api, task);
  } catch (err) {
    thrown.push({
      invariant: "intervention-completed",
      message: `intervention threw: ${err instanceof Error ? err.message : String(err)}`,
    });
  }

  const final = snapshot(db);
  const finalDigest = digest(final);
  db.close();

  const violations = [...thrown, ...verify(initial, final)];

  return ReportSchema.parse({
    case_id: cf.trace.case_id,
    intervention: name,
    passed: violations.length === 0,
    violations,
    initial_digest: initialDigest,
    final_digest: finalDigest,
    checked_at: task.issued_at,
  });
}
