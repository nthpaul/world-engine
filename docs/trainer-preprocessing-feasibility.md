# Offline Trainer Preprocessing Feasibility

Inspected 2026-10-10. This is a bounded feasibility record and gated recommendation, not an implemented trainer adapter. No libraries or model assets were installed or downloaded. No inference, training, paid provider, cloud resource, account, or private-file scan was used.

## Available Runtimes

`pyproject.toml` declares FastAPI, HTTPX, Pydantic, and Uvicorn; development tools are pytest, pytest-asyncio, and Ruff. It declares no tokenizer or training framework.

| Runtime inspected | Python | torch | transformers / TRL / tokenizers | sentencepiece / safetensors / gguf / llama_cpp |
|---|---|---|---|---|
| Project `.venv/bin/python` | 3.13.5 | Absent | All absent | All absent |
| Codex bundled Python, runtime bundle 26.1007.11041 | 3.12.14 | Absent | All absent | All absent |
| `/usr/local/bin/python3` | 3.12.8 | Absent | All absent | All absent |

The bundled runtime contains NumPy. The system runtime contains Jinja2. Neither supplies the missing exact Qwen encoder, and Jinja2 does not execute an Ollama Go template. The inspection used `importlib.util.find_spec`, not package installation. This result covers these three selected runtimes, not every possible environment elsewhere on the machine.

## Installed Public Model Metadata

Metadata-only loopback calls to `/api/tags`, `/api/show` with `verbose: true`, and `/api/version` confirmed Ollama 0.22.0 and the existing public `qwen3:8b` catalog entry:

- Digest: `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Format: GGUF, Q4_K_M, reported parameter size 8.2B; license metadata is Apache 2.0.
- Tokenizer metadata: model `gpt2`, pretokenizer `qwen2`, 151,936 vocabulary entries, 151,387 merges, and 151,936 token-type entries.
- Public chat template: 1,723 characters, Go-template syntax; SHA-256 `ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4`.
- Advertised capabilities: completion, tools, and thinking. This installed response has no explicit `thinking` settings object.

The following IDs were read from this vocabulary and metadata, not guessed:

| Token | ID |
|---|---:|
| `<\|endoftext\|>` | 151643, also configured BOS and padding |
| `<\|im_start\|>` | 151644 |
| `<\|im_end\|>` | 151645, configured EOS |
| `<think>` / `</think>` | 151667 / 151668 |
| `<tool_call>` / `</tool_call>` | 151657 / 151658 |
| `<tool_response>` / `</tool_response>` | 151665 / 151666 |

Only public model metadata was inspected. The model's private filesystem paths and unrelated user files were not read or retained. Large vocabulary/merge arrays were summarized rather than copied into the repository.

The [official show-model endpoint](https://docs.ollama.com/api-reference/show-model-details) documents verbose metadata and the model's prompt template. The [chat endpoint](https://docs.ollama.com/api/chat) documents tool/JSON formats, usage counts, and optional output log-probability fields. These current documents do not prove the installed version supplies sampled token IDs or probabilities for an existing receipt. No capability inference call was made. Accessed 2026-10-10.

## Precise Blocker

Metadata exists, but an exact installed encoder and chat-template executor do not exist in the inspected Python runtimes. Vocabulary IDs and BPE merges alone are not a tested implementation of pretokenization, special-token handling, tool serialization, and template behavior. Reimplementing these by hand would violate the project's requirement to use established domain libraries and would need independent parity testing.

There is also no installed trainer, tensor framework, or demonstrated trainer-compatible model checkpoint. The installed quantized inference artifact must not be called a ready TRL training checkpoint. Readable transcripts and usage counts do not recover the sampled token sequence, behavior-policy probabilities, on-policy checkpoint, or valid action masks needed for PPO/GRPO. JSONL candidate exports remain candidates.

## Minimal Safe Adapter When Prerequisites Exist

Do not implement a toy trainer or text-only imitation of tokenization in this overnight window. Preserve existing selection reports and exact controller/native-wire evidence, and expose no `trainable: true` claim.

A future preprocessing-only adapter can be narrowly scoped to one explicitly supplied, pinned, local tokenizer and template. It should use an established encoder with offline-only asset loading, reject missing assets rather than fetching them, record tokenizer/template digests and special IDs, and produce `input_ids`, `attention_mask`, and assistant-action-only labels with `-100` for system/user/tool-observation spans. It must verify exact template output and role boundaries against known fixtures, preserve task lineage/splits, exclude evaluation-only/private grader data, and fail on unsupported native histories rather than converting them silently.

SFT preprocessing could then be validated without claiming an actual training run. DPO additionally needs a documented comparable-prompt and trajectory serialization contract. PPO/GRPO still requires fresh sampled token/probability capture and a frozen behavior policy; an offline tokenizer cannot manufacture those fields. Authorization to install libraries or acquire compatible assets is a separate future decision, outside the current no-download constraint.
