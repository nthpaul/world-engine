import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { operatorEpisodeJsonl, reserveFreshOutput } from "./ui-qa.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const protocols = ["ollama-tools-v1", "ollama-tools-ledger-v2"];
const receiptLimit = 24 * 1024 * 1024;
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

export function parseOptions(args) {
  const { values } = parseArgs({ args, strict: true, allowPositionals: false,
    options: { "run-id": { type: "string" }, receipt: { type: "string" }, output: { type: "string" } } });
  if (!values["run-id"] || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(values["run-id"]) ||
      !values.receipt?.trim() || !values.output?.trim())
    throw new Error("--run-id, --receipt and an explicit fresh --output are required");
  return { runId: values["run-id"], receipt: path.resolve(values.receipt), output: path.resolve(values.output) };
}

export function localBaseURL(value) {
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) ||
        !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
        url.username || url.password || url.search || url.hash || url.pathname !== "/")
      throw new Error();
    return url.origin;
  } catch {
    throw new Error("Native UI QA requires a loopback browser origin without credentials or URL parameters");
  }
}

function python(code, input, maxBuffer = 32 * 1024 * 1024) {
  try {
    return execFileSync("uv", ["run", "python", "-c", code], {
      cwd: root, input, encoding: "utf8", timeout: 15000, maxBuffer,
    });
  } catch {
    throw new Error("Receipt or operator validation failed; supplied values and subprocess details redacted");
  }
}

export async function preflightReceipt(file) {
  const stat = await lstat(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size === 0 || stat.size > receiptLimit)
    throw new Error("Receipt must be one bounded regular JSONL file, not a symlink");
  const bytes = await readFile(file);
  if (bytes.length > receiptLimit) throw new Error("Receipt exceeds its byte bound");
  const canonicalEpisode = python([
    "import json,sys",
    "from world_engine.models import canonical_json",
    "from world_engine.provider_records import usage_summary",
    "from world_engine.rollout import replay",
    "lines=sys.stdin.read().splitlines()",
    "if len(lines)!=1: raise ValueError('one original wrapper required')",
    "wrapper=json.loads(lines[0]); episode=wrapper['episode']; p=episode['provenance']",
    "if wrapper.get('schema')!='world-engine.evaluation-trace.v1': raise ValueError('wrapper schema')",
    "if wrapper.get('evaluation_only') is not True or wrapper.get('training_eligible') is not False: raise ValueError('wrapper flags')",
    "if wrapper.get('exact_envelope_preserved') is not True: raise ValueError('exact envelope required')",
    "if p.get('evaluation_only') is not True or p.get('training_eligible') is not False: raise ValueError('episode flags')",
    "if p.get('provider_protocol') not in ('ollama-tools-v1','ollama-tools-ledger-v2'): raise ValueError('protocol')",
    "slot=wrapper['slot']",
    "if type(slot.get('index')) is not int or slot['index']<0 or type(slot.get('seed')) is not int: raise ValueError('slot types')",
    "if slot['protocol']!=p['provider_protocol'] or canonical_json(slot['seed'])!=canonical_json(episode['seed']): raise ValueError('slot identity')",
    "if p.get('provider_class')!='world_engine.ollama_tools.OllamaToolsProvider': raise ValueError('native provider required')",
    "if canonical_json(episode['usage'])!=canonical_json(usage_summary(episode['provider_events'])): raise ValueError('usage mismatch')",
    "if replay(episode).get('verified') is not True: raise ValueError('replay')",
    "print(canonical_json(episode))",
  ].join("\n"), bytes).trim();
  const result = { episode: JSON.parse(canonicalEpisode), slot: JSON.parse(bytes.toString("utf8")).slot,
    canonical_episode: canonicalEpisode, episode_sha256: sha256(canonicalEpisode), replay_verified: true };
  assert.ok(protocols.includes(result.episode.provenance.provider_protocol));
  return { ...result, receipt_sha256: sha256(bytes), receipt_bytes: bytes.length, raw: bytes };
}

export async function prepare(options) {
  await reserveFreshOutput(options.output);
  const receipt = await preflightReceipt(options.receipt);
  const baseURL = localBaseURL(process.env.WORLD_ENGINE_UI_URL ?? "http://127.0.0.1:5173");
  return { receipt, baseURL };
}

export function validateApiDetail(receipt, rawDetail, runId) {
  if (Buffer.byteLength(rawDetail) > receiptLimit + 64 * 1024)
    throw new Error("API detail exceeds its bound");
  const detail = JSON.parse(rawDetail);
  assert.equal(detail.id, runId);
  assert.match(detail.label, /^Imported operator receipt\b/);
  assert.equal(detail.config.evaluation_only, true);
  assert.equal(detail.config.episodes, 1);
  assert.equal(detail.episodes.length, 1);
  assert.equal(detail.config.environment_id, receipt.episode.provenance.environment_id);
  assert.equal(detail.config.seed, receipt.episode.seed);
  assert.equal(detail.config.model, receipt.episode.provenance.model);
  assert.equal(detail.config.allow_paid, false);
  assert.equal(detail.status, receipt.episode.status);
  assert.equal(detail.elapsed_seconds, receipt.episode.elapsed_seconds);
  assert.equal(operatorEpisodeJsonl([rawDetail]).trim(), receipt.canonical_episode);
  return detail;
}

export function validateDownload(format, content, receipt, runId) {
  assert.ok(Buffer.byteLength(content) <= receiptLimit);
  const rows = content.trim() ? content.trim().split("\n").map((line) => JSON.parse(line)) : [];
  if (["sft", "dpo", "grpo"].includes(format)) {
    assert.equal(rows.length, 0);
    return rows;
  }
  assert.equal(rows.length, 1);
  const episode = receipt.episode, record = rows[0];
  if (format === "traces") {
    assert.equal(record.schema, "world-engine.trace.v1");
    assert.deepEqual(record.provenance, { ...episode.provenance, episode_id: episode.id, run_id: runId, split: episode.split });
    assert.deepEqual(record.provider_events, episode.provider_events);
    assert.deepEqual(record.provider_recording, episode.provider_recording);
    assert.deepEqual(record.usage, episode.usage);
    assert.deepEqual(record.trace, episode.trace);
    assert.deepEqual(record.initial_observation, episode.initial_observation);
    for (const field of ["reward", "passed", "termination", "final_state_hash"])
      assert.deepEqual(record[field], episode[field]);
    assert.equal(record.training_eligible, false);
    assert.equal(record.provenance.provider_protocol, episode.provenance.provider_protocol);
    assert.equal(record.provenance.evaluation_only, true);
    assert.equal("grader" in record, false);
    assert.equal("initial_snapshot" in record, false);
    assert.equal("final_snapshot" in record, false);
  } else {
    assert.equal(format, "atif");
    assert.equal(record.schema_version, "ATIF-v1.8");
    assert.equal(record.trajectory_id, episode.id);
    assert.equal(record.session_id, runId);
    assert.equal(record.extra.evaluation_only, true);
    assert.equal(record.extra.training_eligible, false);
    const metadata = record.extra.world_engine;
    assert.deepEqual(metadata.provider_events, episode.provider_events);
    assert.deepEqual(metadata.recorded_provider_usage, episode.usage);
    assert.deepEqual(metadata.provenance, episode.provenance);
    for (const field of ["passed", "reward", "status", "termination", "invalid_actions", "seed", "split", "final_state_hash"])
      assert.deepEqual(metadata[field], episode[field]);
    assert.equal("grader" in metadata, false);
    assert.equal("initial_snapshot" in metadata, false);
    assert.equal("final_snapshot" in metadata, false);
    const steps = record.steps.filter((step) => step.source === "agent");
    assert.equal(steps.length, episode.trace.length);
    for (let index = 0; index < steps.length; index++) {
      const step = steps[index], original = episode.trace[index];
      assert.deepEqual(step.extra.policy_input, original.policy_input);
      assert.match(step.extra.policy_input_scope, /not a provider transcript/);
      assert.equal(step.tool_calls[0].function_name, original.action.tool);
      assert.deepEqual(step.tool_calls[0].arguments, original.action.args);
      assert.deepEqual(step.extra.recorded_usage, original.usage);
      assert.equal("timestamp" in step, false);
      for (const [source, target] of [["input_tokens", "prompt_tokens"], ["output_tokens", "completion_tokens"]]) {
        if (source in original.usage) assert.equal(step.metrics[target], original.usage[source]);
        else assert.equal(target in (step.metrics ?? {}), false);
      }
    }
    for (const [source, target] of [["input_tokens", "total_prompt_tokens"], ["output_tokens", "total_completion_tokens"]]) {
      const complete = episode.trace.length > 0 && episode.trace.every((step) => source in step.usage);
      if (complete) assert.equal(record.final_metrics[target], episode.trace.reduce((sum, step) => sum + step.usage[source], 0));
      else assert.equal(target in record.final_metrics, false);
    }
  }
  return rows;
}

export function requestAllowed(baseURL, method, url) {
  return method === "GET" && new URL(url).origin === baseURL;
}

async function controllerSource() {
  const scope = ["src/world_engine", "web/src", "web/package.json", "web/package-lock.json",
    "scripts/ui-qa.mjs", "scripts/native-ui-qa.mjs", "tests/test_native_ui_qa.py", "pyproject.toml", "uv.lock"];
  const git = (args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8", timeout: 3000 }).trim();
  assert.equal(git(["status", "--porcelain", "--untracked-files=all", "--", ...scope]), "",
    "Native UI QA source scope must be committed and clean");
  const files = {};
  for (const file of git(["ls-files", "--", ...scope]).split("\n"))
    files[file] = sha256(await readFile(path.join(root, file)));
  return { revision: git(["rev-parse", "HEAD"]), source_dirty: false, source_dirty_scope: scope, files };
}

async function main(options) {
  const { receipt, baseURL } = await prepare(options);
  const source = await controllerSource();
  const require = createRequire(path.join(root, "web/package.json"));
  const { chromium } = require("playwright");
  const browser = await chromium.launch();
  let context;
  const checks = [], errors = [], blocked = [], downloads = [];
  const check = (name, value) => { assert.ok(value, name); checks.push(name); };
  try {
    context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 960 },
      permissions: ["clipboard-read", "clipboard-write"],
      recordVideo: { dir: path.join(options.output, "video"), size: { width: 1440, height: 960 } } });
    context.setDefaultTimeout(15000);
    await context.route("**/*", async (route) => {
      const request = route.request(), url = new URL(request.url());
      if (!requestAllowed(baseURL, request.method(), request.url())) {
        blocked.push({ method: request.method(), cross_origin: url.origin !== baseURL });
        await route.abort();
      } else await route.continue();
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => errors.push(error.name));
    const runPath = `/api/runs/${encodeURIComponent(options.runId)}`;
    const detailResponse = await context.request.get(runPath, { timeout: 15000, maxRedirects: 0 });
    assert.ok(detailResponse.ok());
    const rawDetail = await detailResponse.text();
    const detail = validateApiDetail(receipt, rawDetail, options.runId);
    check("Imported run preserves the complete episode JSON values, numeric types, ID/index and provenance", true);
    await writeFile(path.join(options.output, "original-receipt.jsonl"), receipt.raw, { flag: "wx" });
    await writeFile(path.join(options.output, "api-detail.json"), rawDetail, { flag: "wx" });
    await page.goto(`/#runs/${encodeURIComponent(options.runId)}`);
    await page.getByRole("heading", { name: detail.label, exact: true }).waitFor();
    check("Run is visibly labelled an imported operator receipt", detail.label.startsWith("Imported operator receipt"));
    const metric = page.locator(".detail-metrics .metric").filter({ hasText: "Step throughput" });
    check("Throughput is explicitly labelled steps/s", (await metric.innerText()).includes("steps/s"));
    check("Inspector preserves actual termination", (await page.locator(".episode-strip").innerText())
      .includes(receipt.episode.termination.replaceAll("_", " ")));
    const shot = async (name) => {
      await page.locator(".toast button").evaluateAll((buttons) => buttons.forEach((button) => button.click()));
      await page.screenshot({ path: path.join(options.output, name), fullPage: false });
    };
    const viewport = async (name) => check(`${name}: no document horizontal overflow`,
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await viewport("Desktop native metrics");
    await shot("desktop-native-metrics.png");
    if (receipt.episode.trace.length) {
      await page.locator(".trace-item").last().click();
      await page.getByRole("button", { name: "Copy action JSON", exact: true }).click();
      await page.getByText("Copied to clipboard.", { exact: true }).waitFor();
      assert.deepEqual(JSON.parse(await page.evaluate(() => navigator.clipboard.readText())), receipt.episode.trace.at(-1).action);
      check("Copy action uses the recorded final decision", true);
      await page.getByText("Provider usage", { exact: true }).click();
      const displayed = JSON.parse(await page.locator(".step-detail details").filter({ hasText: "Provider usage" }).locator("pre").innerText());
      assert.deepEqual(displayed, receipt.episode.trace.at(-1).usage);
      check("Step usage renders only recorded fields", true);
    }
    await viewport("Desktop native trace");
    await shot("desktop-native-trace.png");
    await page.getByRole("tab", { name: "Provenance", exact: true }).click();
    await page.locator(".frozen-provenance summary").first().click();
    const rendered = JSON.parse(await page.locator(".frozen-provenance details[open] pre").innerText());
    assert.deepEqual(rendered.provenance, receipt.episode.provenance);
    assert.deepEqual(rendered.usage, receipt.episode.usage);
    assert.equal(rendered.termination, receipt.episode.termination);
    check("Frozen provenance retains the actual native protocol, contract/module hashes, model digest and usage completeness", true);
    await page.getByRole("button", { name: "Copy metadata", exact: true }).click();
    await page.getByText("Copied to clipboard.", { exact: true }).waitFor();
    const copied = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
    assert.equal(copied[0].id, receipt.episode.id);
    assert.deepEqual(copied[0].provenance, receipt.episode.provenance);
    assert.deepEqual(copied[0].usage, receipt.episode.usage);
    await page.locator(".frozen-provenance").scrollIntoViewIfNeeded();
    await shot("desktop-native-provenance.png");
    for (const format of ["traces", "atif", "sft", "dpo", "grpo"]) {
      await page.getByLabel("Export format").selectOption(format);
      await page.getByLabel("Export quality").selectOption("all");
      const waiting = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const download = await waiting;
      const filename = `${options.runId}-${format}-all.jsonl`;
      await download.saveAs(path.join(options.output, filename));
      const bytes = await readFile(path.join(options.output, filename));
      const direct = await context.request.get(`${runPath}/export?format=${format}&quality=all`, { timeout: 15000, maxRedirects: 0 });
      assert.ok(direct.ok());
      assert.deepEqual(bytes, await direct.body());
      const rows = validateDownload(format, bytes.toString("utf8"), receipt, options.runId);
      assert.equal(direct.headers()["x-export-records"], String(rows.length));
      downloads.push({ format, quality: "all", filename, bytes: bytes.length, sha256: sha256(bytes), rows: rows.length });
      check(`${format}: byte-exact browser download preserves the native operator/training boundary`, true);
    }
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      await page.locator(".detail-metrics").scrollIntoViewIfNeeded();
      await viewport(`Mobile ${width} metrics`);
      check(`Mobile ${width} retains Step throughput and steps/s`, (await metric.innerText()).includes("steps/s"));
      await shot(`mobile-${width}-native-metrics.png`);
      await page.locator(".frozen-provenance").scrollIntoViewIfNeeded();
      await viewport(`Mobile ${width} provenance`);
      await shot(`mobile-${width}-native-provenance.png`);
      await page.getByRole("tab", { name: "Episode traces", exact: true }).click();
      await page.locator(".trace-layout").scrollIntoViewIfNeeded();
      await viewport(`Mobile ${width} trace`);
      await shot(`mobile-${width}-native-trace.png`);
      await page.getByLabel("Export format").scrollIntoViewIfNeeded();
      await viewport(`Mobile ${width} export controls`);
      await shot(`mobile-${width}-native-exports.png`);
      await page.getByRole("tab", { name: "Provenance", exact: true }).click();
    }
    check("No browser runtime errors or non-GET/cross-origin requests", errors.length === 0 && blocked.length === 0);
    const finalSource = await controllerSource();
    assert.deepEqual(finalSource, source);
    const report = { generated_at: new Date().toISOString(), phase: "native-read-only", base_url: baseURL,
      run_id: options.runId, imported_run_label: detail.label, selection_scope: "declared slot for inspection, not performance selection",
      receipt: { file: options.receipt, bytes: receipt.receipt_bytes, sha256: receipt.receipt_sha256,
        episode_sha256: receipt.episode_sha256, slot: receipt.slot, replay_verified: receipt.replay_verified },
      controller_source: source, episode_provenance: receipt.episode.provenance,
      actual_usage: receipt.episode.usage, termination: receipt.episode.termination,
      checks, downloads, browser_errors: errors, blocked_requests: blocked,
      api_mutations: 0, model_calls: 0, paid_calls: 0, new_rollouts: 0,
      evaluation_only: true, training_eligible: false,
      video: await page.video().path(),
      upstream_validation: "ATIF file saved for separate actual pinned Harbor validation; no schema claim made here" };
    await writeFile(path.join(options.output, "ui-report.json"), JSON.stringify(report, null, 2), { flag: "wx" });
    console.log(`Native read-only UI QA passed: ${checks.length} checks; ${receipt.episode.provenance.provider_protocol}; ${options.output}`);
  } catch (error) {
    await writeFile(path.join(options.output, "failure.json"), JSON.stringify({ generated_at: new Date().toISOString(),
      phase: "native-read-only", run_id: options.runId, error_type: error.name, details: "redacted",
      checks, browser_errors: errors, blocked_requests: blocked }, null, 2), { flag: "wx" });
    throw new Error("Native read-only UI QA failed; prior evidence retained; details redacted");
  } finally {
    if (context) await context.close();
    await browser.close();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  await main(parseOptions(process.argv.slice(2)));
