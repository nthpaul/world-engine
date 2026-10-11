# Workflow Variant Evaluation

Reference implementation coverage only. No learned-model score, training, application parity, or speed comparison.

Source: `ee26d7b9e29397e3dcccfc09c664f08dcf3b004c`; implementation scope clean. Protocol: `7876220a33f91c34e58fa8b9853bec1b0ab6bd19c604585eccdb71e3a453d9e0`.

64 unique world/seed tasks, 128 matched attempts, concurrency 1, 20-decision/30-second bounds per attempt. All are evaluation-only. No model calls.

| World | Case | Policy | Passes | Invalid actions |
|---|---|---|---:|---:|
| crm-merge | standard-ownership | scripted-oracle | 8/8 | 0 |
| crm-merge | standard-ownership | scripted-baseline | 0/8 | 8 |
| crm-merge | equal-customer-timestamps | scripted-oracle | 8/8 | 0 |
| crm-merge | equal-customer-timestamps | scripted-baseline | 0/8 | 8 |
| crm-merge | noncanonical-invoice-copies | scripted-oracle | 8/8 | 0 |
| crm-merge | noncanonical-invoice-copies | scripted-baseline | 0/8 | 8 |
| crm-merge | noncanonical-copies-equal-timestamps | scripted-oracle | 8/8 | 0 |
| crm-merge | noncanonical-copies-equal-timestamps | scripted-baseline | 0/8 | 8 |
| refund-ops | standard-capture | scripted-oracle | 4/4 | 0 |
| refund-ops | standard-capture | scripted-baseline | 0/4 | 4 |
| refund-ops | delivery-day-30 | scripted-oracle | 4/4 | 0 |
| refund-ops | delivery-day-30 | scripted-baseline | 0/4 | 4 |
| refund-ops | request-5000-cents | scripted-oracle | 4/4 | 0 |
| refund-ops | request-5000-cents | scripted-baseline | 0/4 | 4 |
| refund-ops | request-5001-cents | scripted-oracle | 4/4 | 0 |
| refund-ops | request-5001-cents | scripted-baseline | 0/4 | 4 |
| refund-ops | delivery-day-31 | scripted-oracle | 4/4 | 0 |
| refund-ops | delivery-day-31 | scripted-baseline | 0/4 | 4 |
| refund-ops | capture-one-cent-less | scripted-oracle | 4/4 | 0 |
| refund-ops | capture-one-cent-less | scripted-baseline | 0/4 | 4 |
| refund-ops | chargeback-record | scripted-oracle | 4/4 | 0 |
| refund-ops | chargeback-record | scripted-baseline | 0/4 | 4 |
| refund-ops | damage-record-unverified | scripted-oracle | 4/4 | 0 |
| refund-ops | damage-record-unverified | scripted-baseline | 0/4 | 4 |

Synthetic policy fixtures, not public real-application tasks.
Case labels are receipt-only and absent from policy observations.
Two policies share each task; they are not independent task samples.
Seed holdout does not establish withheld-case or workflow-family generalization.
Timings are diagnostics under uncontrolled background load, not performance claims.

Full operator traces are evaluation-only. Every attempt replayed under the collected source. New source revisions may require its pinned checkout for replay.
