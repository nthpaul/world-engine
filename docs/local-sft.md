# Private Local SFT Data

This increment prepares original synthetic workflow decisions for a private local
SFT experiment. It does not load model tensors, run inference, train, or produce a
checkpoint. Actual training requires a separately reviewed trainer and explicit
operator authorization after this data stage is verified.

## Plan

```sh
uv run python scripts/local_sft_pilot.py
```

The default prints a fixed plan without files, network contact, episodes or model
loading. Collection uses an operator-created isolated Python environment with
exact binary-package locks, the already-installed model cache, and a reviewed
clean source checkout:

```sh
PYTHONPATH=/ABSOLUTE/PINNED/CHECKOUT/src \
  /ABSOLUTE/PRIVATE/TRAINING-VENV/bin/python \
  /ABSOLUTE/PINNED/CHECKOUT/scripts/local_sft_pilot.py \
  --collect --source-revision REVIEWED_FULL_SHA \
  --output /ABSOLUTE/PRIVATE/NEW-DATA-DIRECTORY
```

The source guard derives the checkout from the script location. It requires the
entire implementation, dependencies, collector, tests and protocol to match the
reviewed commit. Other workers' source changes therefore require a separate
pinned checkout. Existing output directories, files and dangling symlinks are
refused before source, tokenizer or episode activity.

## Data Boundary

`training_data.select_episode` requires current deterministic replay, a clean
business pass, train split, original refund/access world, and the built-in
scripted reference provider. Held-out, evaluation-only, native, recorded HTTP,
browser, failed and invalid traces remain excluded. Reference actions and their
exact recorded public controller messages become three-message decision examples.
Private snapshots and grading checks never enter those examples.

`encode_example` uses the exact cached chat template twice: the generation prefix
and completed assistant response. The prefix must match token-for-token. Prompt
labels are `-100`; only the assistant action and its end delimiter have loss
labels. Oversize decisions are retained as explicit rejections, never truncated.
This token preparation is not on-policy RL: there are no behavior log-probabilities,
sampled-policy checkpoint rollouts, or GRPO training claims.

The original fixture code and reference actions are operator-authorized solely
for this private local experiment and internally retained adapter/data. The
attestation is not an external redistribution license or proof of ownership.
The cached Qwen model has an [Apache 2.0 license at its pinned revision](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/LICENSE);
that license does not grant rights over unrelated benchmark or application data.

## Evidence And Limits

All returned episodes are fsynced to private operator-only JSONL before eligibility
or token validation. That file includes snapshots and is not a training export.
Public decisions, masked examples, rejections, every planned slot and a file/hash
manifest are separate. A stopped prefix is retained without retries. The eight
fixed held-out live-evaluation tasks are selected by seed/split order, not outcomes;
all remaining held-out instances and decisions are counted and retained separately.
This stage does not yet compute held-out token loss or live model outcomes.

Python socket connection guards and Hugging Face offline flags are cooperative
controller protections, not an OS/container egress sandbox. The 600-second stage
deadline and 256 MiB evidence budget are cooperative trusted-work bounds. Source
hashes and replay verify consistency, not signed collection authenticity. Seed
holdout within public synthetic rule families does not establish enterprise or
real-application transfer.

See [the fixed protocol](local-sft-protocol.md).
