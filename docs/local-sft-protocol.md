# Private Original SFT Data Protocol V1

## Fixed Stage One

The committed `scripts/local_sft_pilot.py` plan is authoritative. No model tensor
execution is authorized by invoking this data collector.

| Item | Value |
| --- | --- |
| Worlds | `refund-ops`, then `access-provisioning` |
| Seeds | 60000 through 60063 for each world |
| Episodes | 128 original scripted-reference episodes, sequential |
| Budget | 20 decisions / 30 seconds per episode; 600 seconds aggregate |
| Data split | Existing stable lineage split; train only in supervision files |
| Live held-out subset | First four validation/test seeds per world, fixed order |
| Eligibility | Replay verified, completed/finished, business pass, zero invalid actions |
| Decision size | At most 4096 tokens; reject, never truncate |
| Evidence | 256 MiB combined, 8 MiB admission reserve, 1 MiB final report reserve |
| Retries | None |
| Rights | Original authorized private-local use; redistribution not granted |

The report retains every planned slot, raw finalized episode, failed/rejected
selection, token rejection, unattempted slot, all held-out counts, and the selected
eight-task live evaluation subset. Original evidence is not replaced on failure.
No training-ready claim is made unless at least 32 tokenized decisions and eight
tokenized train instances per world remain, with all eight held-out tasks recorded
and unchanged source. This gate proves dataset availability, not learning.

## Exact Cache And Runtime

No downloads are allowed. The expected cache is the standard local Hugging Face
snapshot for `Qwen/Qwen2.5-0.5B-Instruct` revision
`7ae557604adf67be50417f59c2c2f167def9a775`. All seven files are SHA256 checked,
including weights `fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`.
Weights are read for hashing, not tensor loading.

The package gate requires torch 2.9.0, transformers 4.57.1, peft 0.17.1,
accelerate 1.10.1, tokenizers 0.22.2 and safetensors 0.8.0. The private installation
receipt also pins exact transitive versions and binary wheel hashes. Base SDK
parsing dependencies match the repository's existing `uv.lock`; no training
dependency is added to the project's normal runtime.

The tokenizer is `Qwen2TokenizerFast`, EOS 151645, padding 151643, and chat-template
SHA256 `cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f`.
Every accepted example proves exact prompt-prefix token equality and assistant-only
labels. These are template tokens, not measurements of a serving daemon's context.

## Later Training Gate

An actual checkpoint remains a separate protocol and source review. Proposed
limits are a one-step MPS compatibility smoke followed, only if explicitly
authorized, by 32 optimizer updates using established Trainer/PEFT with rank 8,
alpha 16, `q_proj`/`v_proj`, dropout 0, batch 1, accumulation 4, learning rate
0.0001 and float32 MPS. Device fallback must not silently change the experiment.
The whole pilot is bounded to 40 minutes, training to 15 minutes, output to 4 GiB.
No optimizer, parameter, seed, dataset or budget tuning follows a failure without
a new protocol. Base/final comparison will use all eight declared live held-out
tasks; token-loss evaluation over held-out public decisions is a distinct
denominator and must retain oversize/error exclusions. Exact checkpoint save,
hashes and reload proof are required before claiming a trained artifact.
