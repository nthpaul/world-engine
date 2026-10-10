# Historical Receipt Integrity Note

The adjacent `report.json`, `report.md`, and `traces.jsonl` are immutable workflow version 1.1.0 execution evidence collected from clean source `6cc84237384f04b5a205b04a127ce99ba9ff00d9`. They retain 128 replay-verified scripted attempts and their original outcomes. They are not evidence that every possible state-corruption exploit was rejected.

Subsequent review reproduced a grader gap: after correctly denying an ineligible refund, manually appending a forged approval record could retain a passing grade. The operational tool boundary rejected ineligible approvals, and replay did not accept fabricated transitions. This gap concerned authoritative final-state grading in trusted Python objects, not a demonstrated remote exploit or a failed recorded normal execution.

Refund version 1.1.1 now preserves original approval history and permits at most one new exact target/request finance-reviewer approval only when the original request was eligible. Valid voluntary approval below the role limit remains permitted. New tests cover ineligible approvals, forged reviewer, wrong amount, unrelated order, and duplicates.

Replay these old traces in their recorded source checkout. Whole-module fingerprints also change for CRM and incident records when refund source changes. The corrected collector uses a new `artifacts/workflow-variants/hardened/` directory after its source commit; do not overwrite this historical attempt or describe it as collected with the corrected grader.
