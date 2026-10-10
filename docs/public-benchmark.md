# Public terminal-task evaluation

The standalone runner evaluates the public `log-summary-date-ranges` task from [Terminal-Bench 2](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/log-summary-date-ranges). It uses the unmodified task instruction, deterministic log generator, official solution, and official Python grader from revision `2fd12b88aafdd04a52c298e3940bcb189f9766d6`. The source is vendored under `benchmarks/terminal_bench`, with Apache 2.0 license, author attribution, original canary, and a SHA-256 manifest. The runner checks the manifest before building or executing.

This is evaluation-only. Neither the public task nor its solution, grader, or agent traces are registered with the World Engine training exporter. Public evidence is stored separately in `artifacts/public-benchmark`, and every result is labeled `evaluation_only: true` and `training_eligible: false`. Preserve that exclusion when adding any future artifact importer.

## Run

Docker must be running. For the model attempt, Ollama must serve an already installed `qwen3:8b` model on loopback. No model downloads, external model APIs, or paid calls are performed.

```sh
python3 scripts/public-benchmark.py
python3 -m unittest discover -s tests -p test_public_benchmark.py
```

To verify only the official solution and negative control:

```sh
python3 scripts/public-benchmark.py --skip-local
```

The runner resolves the official `python:3.13-slim-bookworm` image to its digest, generates the original logs at build time, and creates a separate verifier image with `pytest==8.4.1`. Build steps require Docker Hub and PyPI access; episodes and grading run without container networking. Reports record the resolved base digest and actual agent/verifier image IDs. Subsequent runs can use Docker's build cache, though the base tag is resolved again.

## Isolation and bounds

Agent and verifier containers run as UID/GID 65534 with read-only root filesystem, no network, no capabilities, no privilege escalation, 64-process limit, 2 GiB memory limit, and one CPU. `/tmp` is a 32 MiB tmpfs. Kernel file-size limits cap writes at 256 KiB, core dumps are disabled, and Docker logging is disabled. Before evaluation, a fresh agent attempts a 512 KiB write; the report records the actual failure and resulting file size. Actual agent and verifier inspection records include file limits and log configuration. The only agent host bind mount is the fixed `/app/summary.csv` output file inside a private host temporary directory. The agent receives no repository, Docker socket, credentials, official solution, or grader mount. Original logs are baked into the image and read-only.

The local controller allows eight model calls and at most eight shell commands, each limited to 15 seconds and 16 KiB output, under a 180-second episode budget. Local requests use credential-free loopback HTTP, disable redirects and environment proxies, disable thinking, and cap generation at 1024 tokens. The default `native-tools-v2` protocol uses [Ollama native tool calling](https://docs.ollama.com/capabilities/tool-calling) with one validated `shell({command})` or `finish({})` call per turn. Two consecutive protocol errors stop the attempt. Raw calls, bounded outputs, token counts, and latency are retained.

The earlier `json-command-v1` experiment requested a JSON object containing one command. Its preserved receipts show truncated malformed actions, not evidence of business-task incompetence. The native-tool experiment is separately versioned: it executed valid commands but did not produce the requested CSV within eight calls. No further prompt tuning was performed after that task failure. Historical receipts, including the first harness attempt whose raw response was not captured, remain under `attempts`; the missing response is explicitly recorded rather than reconstructed.

The controller removes the agent before reading its fixed regular output file. It rejects symlinks and artifacts larger than 256 KiB. Grading starts in a new container with the clean original image and a read-only copy of the final CSV. The official Python tests are mounted read-only only in that verifier. All episode containers are removed during cleanup.

## Protocol adaptations

The official solution's apt installation line is omitted because grep and coreutils are already present in the base image. Its counting algorithm is unchanged. The official `tests/test_outputs.py` is unchanged. The original `tests/test.sh` downloads curl/uv/pytest at runtime; this runner instead preinstalls pytest 8.4.1 during the verifier image build and invokes `python -m pytest -p no:cacheprovider /tests/test_outputs.py -rA` directly.

The negative policy deliberately writes a malformed, wrong-count CSV. The reference must pass the original grader and the negative control must fail, or the runner exits with an error. A model failure remains a recorded evaluation outcome. Reports are not Terminal-Bench leaderboard results and do not support a speed comparison or a claim about general agent competence.

The machine-readable report and Markdown results are saved alongside each policy's final CSV and copied into a unique attempt directory. They include task provenance, image IDs, controller hash, Git HEAD revision and source/worktree dirty flags, runtime inspection, command traces, model metadata, grader output, errors, and elapsed time. Source dirty flags cover only the runner, its tests, and vendored benchmark files; unrelated evidence collection can make the overall worktree dirty. Docker images remain in the local image cache; containers do not remain running.
