# Scripted candidate corpus results

The separate [candidate protocol](scripted-candidate-corpus.md) completed all
128 scripted episodes on 2026-10-10. Each of the 64 exact tasks has an oracle
success and a baseline business failure. The resulting candidates contain
397 exact-context SFT decisions, 51 comparable DPO pairs and 51 grouped records.
No model, tokenizer or trainer ran. These candidates establish export correctness,
not improved model performance.

## Collection and outcomes

The [manifest](../artifacts/candidate-corpus/20261010-v1/manifest.json) pins source
`5e5eb0d94b504e84a0d903811ad60ae5ca602c95` and protocol
`d0b3a3c0c8ef9578f9d754ce137f4ca736db5f7a200d5acd22044907b2d49c2f`.
Its 21 captured source files were clean at collection. Unrelated documentation
and evidence made the overall checkout dirty; the manifest reports both facts.

Four synthetic worlds used seeds `50000..50015`, with one oracle and one baseline
episode per world/seed. All 128 episodes finalized and passed replay verification.
The eight run rows completed, with no retries, stopped collection, inconclusive
episodes or unattempted slots. Total elapsed collector time was 11.456073 seconds
for 620 decisions, including collection, verification and exports. This is a
local scripted measurement, not model-inference throughput.

| World | Oracle business and clean passes | Baseline business passes | SFT decisions | DPO pairs and groups |
|---|---:|---:|---:|---:|
| CRM merge | 16/16 | 0/16 | 76 | 12 |
| Refund operations | 16/16 | 0/16 | 37 | 13 |
| Incident control | 16/16 | 0/16 | 104 | 13 |
| Access provisioning | 16/16 | 0/16 | 180 | 13 |

All 64 pairs are complete, comparable and have distinct action trajectories.
Business failure does not imply numeric reward zero in the three legacy shaped
worlds. The exporter separately checked that each clean chosen trajectory had
strictly higher reward than its matched rejected trajectory.

## Splits and export meaning

Stable lineage assignment produced 51 training tasks, six validation tasks and
seven test tasks. Their paired episodes total 102, 12 and 14 respectively.
These are seed holdouts within public task families, not withheld families.
The declared receipt roots contained no recorded seed overlap before collection;
this scan is not a global proof of unseen data.

The [SFT file](../artifacts/candidate-corpus/20261010-v1/sft.jsonl) contains the exact
recorded controller context and action for each selected decision. It does not
replace the context with a later reconstruction or include protected snapshots.
The [DPO file](../artifacts/candidate-corpus/20261010-v1/dpo.jsonl) contains matched
trajectory preferences, which still need a trainer-specific completion adapter.
The [grouped file](../artifacts/candidate-corpus/20261010-v1/grouped-rollouts.jsonl)
has `trainable=false` and `policy_consistent=false` throughout. Its oracle/baseline
mixtures are not on-policy GRPO samples. Token IDs, action masks, behavior
logprobs and checkpoint identity remain absent; the manifest's
`trainer_token_count` is `null`.

Each export excluded the 13 heldout oracle cases. The raw operator records retain
both policies on every heldout task and all baseline failures. Do not feed those
operator records or heldout cases into a trainer.

## Independent verification and storage

Two reviewers separately replayed all 128 episodes and validated 128 ATIF
documents against the actual Harbor 0.24.0 model. They checked source fingerprints,
slot order, task identity, split/outcome types, exact contexts, strict preference
comparability and artifact accounting. One rebuilt the exports with the exporter;
the other reconstructed expected records without calling that exporter. Both
matched all three files byte for byte. The
[validation sidecar](../artifacts/candidate-corpus/20261010-v1/independent-validation.json)
records the upstream schema pin and file hashes. These checks establish trusted
envelope and transition consistency, not signed collection authenticity.

The original five collection files total 19,021,481 bytes. The private SQLite
database is 9,650,176 bytes with DELETE journaling, successful integrity checks
and no foreign-key violations. The three exports total 9,222,182 bytes. The
sampled journal peak was 33,344 bytes; sampling does not establish continuous
journal telemetry. All original collection bytes remain unchanged.

SQLite stays local and is excluded from Git. The published
[compressed operator archive](../artifacts/candidate-corpus/20261010-v1/candidate-episodes.jsonl.gz)
contains all 128 exact SQLite `data` rows ordered by `run_id, episode_index`,
not chronological collection order. It expands to 9,344,170 bytes and includes
protected synthetic snapshots for auditing, not training. The later archive
and validation sidecar are outside the original collector byte accounting.

For historical replay, use the recorded source revision in a separate checkout,
decompress the operator archive into a fresh file and run the CLI `replay` command.
Adapter or world fingerprint changes can correctly reject old receipts on a newer
checkout. The original output directory must not be reused for collection. A new
collection needs a separately reviewed protocol, fresh seeds and output path;
do not relabel evaluation-only records or retry selected failures into this batch.

This is a small synthetic candidate set with scripted supervision. It does not
establish training rights for external data, enterprise fidelity, calibrated
shaped rewards, generalization or improvement over another infrastructure system.
