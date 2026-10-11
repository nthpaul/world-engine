# Private Local LoRA Pilot V1

This is an executable protocol, not a completed training result. The default
`scripts/local_sft_train.py` prints its plan without files, library tensor imports,
network, model loading, inference or training. Physical execution requires explicit
operator approval after source and protocol review, followed by separate smoke and
final-run authorizations. Do not run either while another model or GitLab cohort
uses the machine.

## Inputs Fixed Before Model Outcomes

The only accepted stage-one report has SHA256
`8ef491474ca183b6622381db99c466ebcec32e366f809e7644504cbdcbcd1b41`, collected
at source `a8b95a4df7a39d6e2884048fbf39c49095487bde`. It contains 128 reference
episodes, 815 masked train decisions from 102 train instances (51 per world),
26 held-out instances and 221 held-out decisions. Independent validation checks
every source blob, original artifact, episode replay and exact token/label record.
The original private evidence is never rewritten or used for a training export.

The length receipt reported access decisions at 1,398–3,443 tokens and refund
decisions at 832–1,111 tokens, with no token rejection. Only these lengths informed
the fixed limits below, not any learned-model outcome. The source report fixes
eight live-evaluation tasks: refund seeds 60003, 60006, 60008, 60010 and access
seeds 60002, 60005, 60007, 60008. The first four held-out seeds per world were chosen
before outcomes, not by model performance. They are seed holdouts in existing
public synthetic rule families, not unseen-rule or enterprise transfer tests.

## Fixed Execution

| Setting | Value |
| --- | --- |
| Base | Installed Qwen2.5-0.5B-Instruct, pinned cache and seven file hashes |
| Device / dtype | MPS / float32; eager attention; no CPU fallback |
| MPS allocator | 0.5 × device-recommended maximum; not a whole-host quota |
| Activation memory | Gradient checkpointing enabled, `use_reentrant=False` |
| LoRA | Rank 8, alpha 16, q_proj/v_proj, dropout 0, no trainable bias |
| Optimizer | Trainer AdamW, learning rate 0.0001, constant schedule, weight decay 0 |
| Gradient norm | 1 |
| Seed | 20261011 for initialization and data sampler |
| Smoke | One optimizer update, batch 1, accumulation 1, first stored train decision |
| Final | 32 optimizer updates, batch 1, accumulation 4 |
| Sampling | Trainer's seeded decision sampler, no outcome-driven balancing |
| Context | At most 4,096 exact input tokens; reject, never truncate |
| Live generation | Greedy, at most 128 new tokens, KV cache enabled |
| Live task budget | 20 decisions / 60 seconds, sequential |
| Whole run | 2,400-second supervised child-process budget |
| Training phase | 900 seconds checked between optimizer/accumulation steps |
| Evidence/checkpoint cap | 4 GiB, cooperative sampled quota with report headroom |
| Retries / fallback | None |

The smoke does not evaluate held-out business outcomes. It proves one finite
optimizer update, changed adapter, unchanged frozen base, a saved adapter and a
fresh base-plus-adapter reload with exact parameter equality and last-token logits
within absolute/relative 0.00001 tolerance. Success does not automatically launch
the final run. A failure is preserved and requires a separately declared intervention.

The final run evaluates all 221 held-out public reference decisions before and
after training, excluding oversized contexts with explicit counts rather than
truncation. These labels live in a separate evaluation-only path and never pass
through train selection or enter the Trainer dataset. Loss is weighted by the
number of assistant action/end-delimiter tokens, distinct from business success.
The final run also executes all eight fixed tasks once with base and once with
the fixed final adapter. All 16 outcome slots remain in the report, including
failed, partial, budgeted, attempted or unattempted slots. Model outputs are strict
JSON actions; malformed JSON is a provider failure, whereas a parsed unauthorized
tool action is an environment rejection. Their counts must not be conflated.

Periodic Trainer evaluation, best-model selection, checkpoint saving and external
reporting are disabled. Only the fixed final adapter is saved; no checkpoint or
hyperparameter is selected on held-outs. Collation journals identify prepared
training batches, not independently proven optimizer consumption. Optimizer step
count, finite losses, changed adapter and whole frozen-base hashes are separate
proofs. A saved checkpoint can be real even if it learns nothing useful.

## Commands And Evidence

```sh
PYTHONPATH=/ABSOLUTE/PINNED/CHECKOUT/src \
  /ABSOLUTE/PRIVATE/TRAINING-VENV/bin/python \
  /ABSOLUTE/PINNED/CHECKOUT/scripts/local_sft_train.py --mode smoke
```

Physical execution, only after authorization:

```sh
PYTHONPATH=/ABSOLUTE/PINNED/CHECKOUT/src \
  /ABSOLUTE/PRIVATE/TRAINING-VENV/bin/python \
  /ABSOLUTE/PINNED/CHECKOUT/scripts/local_sft_train.py \
  --collect --mode smoke --source-revision REVIEWED_FULL_SHA \
  --dataset /ABSOLUTE/PRIVATE/IMMUTABLE-DATA-V1 \
  --data-report-sha256 8ef491474ca183b6622381db99c466ebcec32e366f809e7644504cbdcbcd1b41 \
  --confirm-protocol SHA_FROM_REVIEWED_SMOKE_PLAN \
  --output /ABSOLUTE/PRIVATE/FRESH-SMOKE-OUTPUT
```

Final training uses `--mode train`, its separately reviewed plan digest and a
different fresh output directory. No command downloads weights or enables hosted
inference. The private wheel lock pins binary packages; cache and template hashes
are checked before tensors. Current source must be clean and match the reviewed
full commit; stage-one original files and committed blobs are checked before and
after execution. Python socket guards plus Hugging Face offline flags are
cooperative protections, not OS egress isolation.

An existing output leaf or any symlink ancestor is refused before source/data
preflight or child launch. Worker mode also checks ancestors before reading its
supervisor intent. These checks assume a trusted local filesystem; they are not
protection against a hostile process racing directory replacement.

The parent fsyncs intent before starting the owned child. It enforces the whole-run
deadline, samples output size, and terminates the child's process group on timeout,
operator cancellation or quota overflow. Controller/host death can still leave
uncertainty; this is not daemon TTL or a filesystem quota. The 900-second training
guard cannot preempt a hung native kernel; the parent whole-run stop is the stronger
boundary. Synchronous generation similarly makes per-episode timeouts cooperative.

Private journals retain public model messages, input/generated token IDs and raw
reply text before strict action validation. Checkpoint hashes, dependency versions,
sampled MPS allocation/driver memory, RSS peak, logs, source identities and original
data preservation are recorded. The worker manifest excludes its still-growing
execution log; the parent manifest hashes that log only after child exit. Reports
and manifests do not cryptographically authenticate collection. These private
original-data rights do not grant public redistribution, and no PPO/GRPO capability
is claimed: generation token IDs alone do not supply behavior log-probabilities or
an on-policy training contract.
