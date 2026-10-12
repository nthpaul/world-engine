"""Four fixed, local inference requests; never execute a browser action."""

from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from collect_gitlab_triage import MODELS, reserve_output, sha, source_identity, write

from world_engine.browser_contracts import BrowserObservation
from world_engine.browser_driver import allowed_app_url
from world_engine.browser_policy import (
    BROWSER_TOOLS,
    OPTIONS,
    PROTOCOL,
    REQUEST_LIMIT,
    OllamaBrowserPolicy,
    ax_nodes,
)
from world_engine.browser_store import content_hash
from world_engine.models import canonical_json

SCHEMA = "world-engine.browser-loop-diagnostic.v1"
ENDPOINT = "http://127.0.0.1:11434"
LIMIT = 16 * 1024 * 1024
STEP = 13
ARCHIVED_ATTEMPT = "642ee1fd-0079-4b55-92d7-4978a8142a1a"
ARCHIVED_INPUT_BYTES = 749066
ARCHIVED_INPUT_SHA256 = "de94a2b141116de7e994402a7ca503fea6d419e51bbba047bd4bccea6a218336"
ARCHIVED_REQUEST_SHA256 = "bae172d3c9ea22bb241066c5f13ec171aeaa6f5a69d785184ed10e04390c4c3b"
CELLS = (("archived-8b", "archived-v2", "qwen3:8b"),
         ("corrected-8b", "corrected-v3", "qwen3:8b"),
         ("archived-32b", "archived-v2", "qwen3:32b"),
         ("corrected-32b", "corrected-v3", "qwen3:32b"))


def plan():
    return {"schema": SCHEMA, "cells": [dict(zip(("name", "context", "model"), cell)) for cell in CELLS],
            "models": MODELS, "archived_attempt_id": ARCHIVED_ATTEMPT, "completed_steps": STEP,
            "archived_input_bytes": ARCHIVED_INPUT_BYTES, "archived_input_sha256": ARCHIVED_INPUT_SHA256,
            "remaining_actions": 17, "archived_request_sha256": ARCHIVED_REQUEST_SHA256,
            "corrected_protocol": "ollama-browser-tools-v3", "options": dict(OPTIONS),
            "think": False, "max_calls": 4, "automatic_retries": 0,
            "cell_seconds": 180, "close_seconds": 3, "max_total_seconds": 780,
            "finalization_reserve_seconds": 30, "max_artifact_bytes": LIMIT,
            "browser_actions_executed": 0, "paid_calls": False, "training_eligible": False,
            "criterion": "valid current-node Click385 versus another valid permitted action; not task success",
            "archived_32b_change": "model field only; not byte-identical to the archived 8B request"}


def save(output, path, value):
    write(output, path, (canonical_json(value) + "\n").encode(), limit=LIMIT)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("non-finite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def public_context(path):
    """Project linked public events, never task fixtures, grades or sealed state."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("a bounded regular archived attempt file is required")
    raw = path.read_bytes()
    if len(raw) != ARCHIVED_INPUT_BYTES or sha(raw) != ARCHIVED_INPUT_SHA256:
        raise ValueError("archived input bytes differ from the reviewed original")
    attempt = strict_json(raw)
    if (attempt["id"] != ARCHIVED_ATTEMPT or attempt["config"]["max_steps"] != 30
            or attempt["config"]["model"] != "qwen3:8b"):
        raise ValueError("diagnostic requires the preregistered archived attempt")
    previous, observations, history, actions = "0" * 64, {}, [], {}
    archived = None
    intents = 0
    for index, original in enumerate(attempt["journal"]):
        record = dict(original)
        stored = record.pop("content_hash")
        if (record["schema"] != "world-engine.browser.v1" or record["attempt_id"] != ARCHIVED_ATTEMPT
                or type(record["sequence"]) is not int
                or record["sequence"] != index or record["previous_hash"] != previous
                or content_hash(record) != stored):
            raise ValueError("archived journal integrity differs")
        previous = stored
        data = record["data"]
        if record["event"] == "observation":
            step = data["step"]
            if type(step) is not int or step != len(observations):
                raise ValueError("public observations must be contiguous")
            observations[step] = BrowserObservation.model_validate(data["observation"]).model_dump()
            if step and len(history) == step:
                history[-1]["observation"] = observations[step]
        elif record["event"] == "action_intent":
            actions[data["step"]] = data["action"]
        elif record["event"] == "action_result":
            step = data["step"]
            if (type(step) is not int or step != len(history) or data["action"] != actions.get(step)
                    or type(data["result"]) is not dict):
                raise ValueError("completed action/result linkage differs")
            history.append({"step": step, "action": data["action"], "result": data["result"]})
        elif record["event"] == "inference_intent":
            if intents == STEP:
                archived = data
                break
            intents += 1
    if archived is None or len(history) != STEP or len(observations) != STEP + 1:
        raise ValueError("archived decision context is incomplete")
    encoded = canonical_json(archived["request_body"]).encode()
    if (sha(encoded) != ARCHIVED_REQUEST_SHA256 or archived["request_sha256"] != sha(encoded)
            or archived["request_bytes"] != len(encoded) or archived["model_digest"] != MODELS["qwen3:8b"]):
        raise ValueError("archived request bytes differ from the preregistration")
    old = archived["request_body"]
    user = strict_json(old["messages"][-1]["content"])
    current = observations[STEP]
    expected_view = {key: current[key] for key in ("url", "title", "observation_mode", "image_not_sent_to_model")}
    expected_view.update(accessibility_text=current["accessibility_text"][:32000],
                         accessibility_truncated=len(current["accessibility_text"]) > 32000)
    if (user != {"task": attempt["task"]["instruction"], "observation": expected_view,
                 "history": [{"action": row["action"], "result": row["result"]} for row in history[-12:]]}
            or old["model"] != "qwen3:8b" or old["options"] != OPTIONS or old["think"] is not False):
        raise ValueError("archived request does not correspond to linked public context")
    return {"input_sha256": sha(raw), "input_bytes": len(raw), "prefix_hash": previous,
            "instruction": user["task"], "observation": current, "history": history,
            "archived_request": old, "completed_steps": STEP, "max_steps": 30}


def requests(context):
    if PROTOCOL != "ollama-browser-tools-v3":
        raise RuntimeError("the corrected v3 policy must be reviewed and present")
    result = {}
    for name, kind, model in CELLS:
        if kind == "archived-v2":
            body = copy.deepcopy(context["archived_request"])
            body["model"] = model
        else:
            # Pure request reconstruction: no client, prepare, inference or reset.
            policy = OllamaBrowserPolicy.__new__(OllamaBrowserPolicy)
            policy.prepared_model, policy.instruction, policy.max_steps = model, context["instruction"], 30
            body = policy.request_body(BrowserObservation.model_validate(context["observation"]), context["history"])
        encoded = canonical_json(body).encode()
        if len(encoded) > REQUEST_LIMIT:
            raise ValueError("diagnostic request exceeds the provider bound")
        result[name] = encoded
    return result


def classify(raw, model, observation):
    try:
        data = strict_json(raw)
        message = data["message"]
        calls = message["tool_calls"]
        if (data.get("model") != model or data.get("done") is not True or data.get("done_reason") != "stop"
                or data.get("remote_host") or data.get("remote_model") or message.get("role") != "assistant"
                or type(calls) is not list or len(calls) != 1):
            raise ValueError
        function = calls[0]["function"]
        name, args = function["name"], function["arguments"]
        if name not in BROWSER_TOOLS or type(args) is not dict or "kind" in args:
            raise ValueError
        action = BROWSER_TOOLS[name][0].model_validate(args).model_dump()
        if "bid" in action:
            matches = [node for node in ax_nodes(observation["accessibility_text"]) if node["bid"] == action["bid"]]
            if len(matches) != 1:
                raise ValueError
        if action["kind"] == "navigate":
            destination, current = urlsplit(action["url"]), urlsplit(observation["url"])
            if ((destination.scheme, destination.netloc) != (current.scheme, current.netloc)
                    or not allowed_app_url(action["url"], observation["url"], document=True)):
                raise ValueError
        usage = {key: data[key] for key in ("prompt_eval_count", "eval_count", "total_duration")
                 if type(data.get(key)) is int and 0 <= data[key] <= 2**63 - 1}
        return {"classification": "repeated_click" if action == {"kind": "click", "bid": "385"} else "other_valid_action",
                "action": action, "usage": usage,
                "token_usage_complete": "prompt_eval_count" in usage and "eval_count" in usage}
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return {"classification": "invalid_response", "token_usage_complete": False}


def require_reply_identity(raw, model):
    try:
        data = strict_json(raw)
    except (ValueError, TypeError, RecursionError):
        return  # Malformed complete replies are recorded diagnostic outcomes.
    if type(data) is dict and (data.get("model") != model or data.get("remote_host") or data.get("remote_model")):
        raise ValueError("reply cannot certify the fixed local model identity")


async def collect(output, revision, input_path):
    output = reserve_output(output)
    report = {**plan(), "status": "started", "chat_attempts": 0,
              "cells": [{"name": cell[0], "status": "unattempted"} for cell in CELLS]}
    started = time.monotonic()
    deadline = started + 780
    try:
        source = source_identity(revision)
        context = public_context(input_path)
        bodies = requests(context)
        report["source"] = source
        report["input"] = {key: context[key] for key in ("input_sha256", "input_bytes", "prefix_hash")}
        save(output, output / "protocol.json", plan())
        save(output, output / "public-context.json", {key: context[key] for key in ("instruction", "observation", "history")})
        templates = {}
        for index, (name, kind, model) in enumerate(CELLS):
            if source_identity(revision) != source or deadline - time.monotonic() < 213:
                raise RuntimeError("source drift or insufficient finalization reserve")
            cell = report["cells"][index]
            cell.update(context=kind, model=model, model_digest=MODELS[model], status="preparing")
            policy = OllamaBrowserPolicy(model, context["instruction"], max_steps=30)
            cell_started = time.monotonic()
            try:
                async with asyncio.timeout(180):
                    if policy.endpoint != ENDPOINT:
                        raise ValueError("only the fixed local daemon is allowed")
                    policy.client.timeout = httpx.Timeout(180)
                    await policy.prepare()
                    metadata = policy.evidence_metadata
                    template = metadata.get("template_sha256", "")
                    if (policy.digest != MODELS[model] or not re.fullmatch(r"[0-9a-f]{64}", template)
                            or templates.get(model, template) != template):
                        raise ValueError("fixed local identity or template changed")
                    templates[model] = template
                    cell["prepared"] = {key: metadata[key] for key in ("model_digest", "template_sha256", "protocol", "ollama_version")}
                    directory = output / name
                    encoded = bodies[name]
                    write(output, directory / "request.json", encoded, limit=LIMIT)
                    cell.update(request_sha256=sha(encoded), request_bytes=len(encoded),
                                request_relation="exact archived bytes" if name == "archived-8b" else
                                "archived bytes with model field substitution" if kind == "archived-v2" else "corrected v3 reconstruction")
                    save(output, directory / "intent.json", {key: cell[key] for key in
                         ("request_sha256", "request_bytes", "request_relation", "prepared")})

                    def transport(kind, payload):
                        if kind == "inference_transport_failure":
                            prefix = base64.b64decode(payload["partial_body_b64"], validate=True)
                            write(output, directory / "response-prefix.bin", prefix, limit=LIMIT)
                            cell["transport_failure"] = {key: payload[key] for key in
                                 ("status", "body_bytes", "body_sha256", "complete_reply_certified")}

                    policy.set_recorder(transport)
                    if source_identity(revision) != source:
                        raise RuntimeError("source drift before chat")
                    if await policy._model_identity(model) != MODELS[model]:
                        raise ValueError("fixed local identity changed before chat")
                    cell["status"] = "chat_started"
                    cell["chat_attempted"] = True
                    report["chat_attempts"] += 1
                    raw = await policy._read("POST", "/api/chat", encoded)
                    write(output, directory / "response.bin", raw, limit=LIMIT)
                    cell.update(response_bytes=len(raw), response_sha256=sha(raw))
                    require_reply_identity(raw, model)
                    if await policy._model_identity(model) != MODELS[model]:
                        raise ValueError("fixed local identity changed after chat")
                    cell.update(classify(raw, model, context["observation"]), status="completed")
            except BaseException as error:
                cell.update(status="failed", error_category=type(error).__name__)
                # A returned/partial transport failure cannot certify stopped daemon generation.
                # Keep its prefix and stop admission of later cells, rather than silently retrying.
                raise
            finally:
                try:
                    async with asyncio.timeout(3):
                        await policy.close()
                    cell["cleanup"] = "completed"
                except Exception as error:
                    cell["cleanup"] = "timeout" if isinstance(error, TimeoutError) else "failed"
                cell["elapsed_seconds"] = time.monotonic() - cell_started
            if cell["cleanup"] != "completed":
                raise RuntimeError("provider resource closure uncertain")
        if source_identity(revision) != source:
            raise RuntimeError("source drift after finalization")
        report["status"] = "completed"
    except BaseException as error:
        report.update(status="stopped", error_category=type(error).__name__,
                      diagnostic="Stopped without retry; completed, failed and unattempted cells retained.")
    report["elapsed_seconds"] = time.monotonic() - started
    save(output, output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    if not args.collect:
        print(json.dumps(plan(), indent=2))
        return
    if args.input is None or args.output is None or args.source_revision is None:
        parser.error("collection requires private --input, fresh --output and reviewed --source-revision")
    report = asyncio.run(collect(args.output, args.source_revision, args.input))
    print(json.dumps({"status": report["status"], "chat_attempts": report["chat_attempts"]}))
    if report["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
