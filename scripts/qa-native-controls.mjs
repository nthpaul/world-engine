import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { lstat, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { reserveFreshOutput } from "./ui-qa.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
export const ARTIFACT_CAP = 64 * 1024 ** 2;
export const REPORT_RESERVE = 1024 ** 2;
export const OVERALL_MS = 120000;
const FINALIZE_MS = 15000;
const PROTOCOL = {
  id: "native-controls-read-only-v1",
  viewports: [{ width: 1440, height: 960 }, { width: 390, height: 844 }, { width: 360, height: 844 }],
  providers: ["local-tools", "local-tools-ledger"],
  model: "qwen3:8b",
  legacy_default_concurrency: 4,
  native_default_concurrency: 1,
  explicit_native_concurrency: 2,
  evaluation_only: true,
  health_version: "0.1.0",
  allowed_methods: ["GET"],
  allowed_api_paths: ["/api/health", "/api/providers", "/api/environments", "/api/runs"],
  overall_ms: OVERALL_MS,
  finalization_reserve_ms: FINALIZE_MS,
  artifact_cap_bytes: ARTIFACT_CAP,
  report_reserve_bytes: REPORT_RESERVE,
  new_rollouts: 0,
  downloads: 0,
  imports: 0,
  inference_requests: 0,
};
const PROTOCOL_SHA256 = "d05f475561417eafb642317e84a1297e001c70eddbf4da6e62bfa1f46753ec77";

export function plan() {
  assert.equal(sha256(JSON.stringify(PROTOCOL)), PROTOCOL_SHA256);
  return { schema: "world-engine.native-controls-plan.v1", protocol: structuredClone(PROTOCOL),
    protocol_sha256: PROTOCOL_SHA256,
    status: "plan-only; no source commands, browser, output, API or model contact" };
}

export function parseOptions(args) {
  try {
    const { values } = parseArgs({ args, strict: true, allowPositionals: false,
      options: { plan: { type: "boolean" }, collect: { type: "boolean" }, output: { type: "string" },
        "source-revision": { type: "string" }, "api-startup-revision": { type: "string" } } });
    if (values.plan && values.collect) throw new Error();
    if (!values.collect) {
      if (values.output !== undefined || values["source-revision"] !== undefined || values["api-startup-revision"] !== undefined)
        throw new Error();
      return { collect: false };
    }
    if (!values.output?.trim() || !/^[a-f0-9]{40}$/.test(values["source-revision"] ?? "") ||
        (values["api-startup-revision"] !== undefined && !/^[a-f0-9]{40}$/.test(values["api-startup-revision"])))
      throw new Error();
    return { collect: true, output: path.resolve(values.output), revision: values["source-revision"],
      apiStartupRevision: values["api-startup-revision"] ?? null };
  } catch {
    throw new Error("Use --plan or --collect with a reviewed full --source-revision and fresh --output; supplied values redacted");
  }
}

export function localOrigin(value) {
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
        url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error();
    return url.origin;
  } catch {
    throw new Error("Controls QA requires a loopback origin without credentials or URL parameters");
  }
}

export function requestAllowed(baseURL, method, value, redirected = false) {
  try {
    const url = new URL(value);
    return !redirected && method === "GET" && url.origin === baseURL && !url.username && !url.password &&
      (!url.pathname.startsWith("/api/") || PROTOCOL.allowed_api_paths.includes(url.pathname));
  } catch {
    return false;
  }
}

export function readOnlyRoute(baseURL, report) {
  return async (route) => {
    const request = route.request();
    const redirected = Boolean(request.redirectedFrom());
    if (!requestAllowed(baseURL, request.method(), request.url(), redirected)) {
      report.blocked_requests.push({ method: request.method(), redirected });
      await route.abort();
      return;
    }
    const pathname = new URL(request.url()).pathname;
    const label = pathname.startsWith("/api/") ? pathname : "<ui-asset>";
    report.requests.GET += 1;
    report.get_paths[label] = (report.get_paths[label] ?? 0) + 1;
    // Fetch without redirect following so a redirect never reaches a second origin.
    try {
      const response = await route.fetch({ maxRedirects: 0, timeout: 5000 });
      if (response.status() >= 300 && response.status() < 400 || new URL(response.url()).origin !== baseURL) {
        report.blocked_requests.push({ method: "GET", redirected: true });
        await route.abort();
        return;
      }
      await route.fulfill({ response });
    } catch {
      report.browser_errors.push("GET fetch failed; details redacted");
      await route.abort();
    }
  };
}

export function verifySourceIdentity(expected, source) {
  if (source.revision !== expected || source.source_dirty !== false || !Object.keys(source.files).length)
    throw new Error("Controls QA source must match the reviewed committed clean scope");
  return source;
}

async function sourceIdentity(expected) {
  const scope = ["src/world_engine", "web/src", "web/package.json", "web/package-lock.json", "web/vite.config.ts", "web/index.html", "pyproject.toml", "uv.lock",
    "scripts/ui-qa.mjs", "scripts/qa-native-controls.mjs", "tests/test_native_controls_qa.py", "docs/native-controls-qa-protocol.md"];
  try {
    const git = (args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8", timeout: 3000 }).trim();
    const revision = git(["rev-parse", "HEAD"]);
    const source_dirty = Boolean(git(["status", "--porcelain", "--untracked-files=all", "--", ...scope]));
    const checkout_dirty = Boolean(git(["status", "--porcelain", "--untracked-files=all"]));
    const files = {};
    for (const name of scope) {
      const absolute = path.join(root, name);
      const info = await lstat(absolute);
      const names = info.isDirectory() ? (await readdir(absolute, { recursive: true })).map((entry) => path.join(name, entry)) : [name];
      for (const entry of names.sort()) {
        const stat = await lstat(path.join(root, entry));
        if (stat.isFile() && (name !== "src/world_engine" || entry.endsWith(".py")))
          files[entry] = sha256(await readFile(path.join(root, entry)));
      }
    }
    return verifySourceIdentity(expected, { revision, source_dirty, checkout_dirty, scope, files });
  } catch {
    throw new Error("Controls QA source gate failed; subprocess details redacted");
  }
}

export async function artifactBytes(output) {
  let bytes = 0;
  for (const entry of await readdir(output, { recursive: true })) {
    const info = await lstat(path.join(output, entry));
    if (info.isSymbolicLink()) throw new Error("Unexpected symlink in reserved QA output");
    if (info.isFile()) bytes += info.size;
  }
  return bytes;
}

export async function writeBounded(output, name, bytes, reserve = REPORT_RESERVE) {
  if (path.basename(name) !== name || await artifactBytes(output) + bytes.length + reserve > ARTIFACT_CAP)
    throw new Error("Controls QA artifact cap reached; existing evidence retained");
  await writeFile(path.join(output, name), bytes, { flag: "wx" });
}

export async function publishVideo(output, videoPath) {
  const info = await lstat(videoPath);
  if (!info.isFile() || info.size + await artifactBytes(output) + REPORT_RESERVE > ARTIFACT_CAP)
    throw new Error("Final video does not fit published artifact cap");
  await writeBounded(output, "controls.webm", await readFile(videoPath));
}

export function workTimeLeft(started, now = Date.now()) {
  const value = started + OVERALL_MS - FINALIZE_MS - now;
  if (value <= 0) throw new Error("Controls QA work deadline reached");
  return value;
}

export function checkMetadata(health, catalog) {
  assert.equal(health.status, "ok");
  assert.equal(health.version, PROTOCOL.health_version);
  assert.equal(health.paid_calls_enabled, false);
  assert.equal(health.active_runs, 0);
  assert.equal(health.max_global_concurrency, 8);
  return PROTOCOL.providers.map((id) => {
    const row = catalog.providers.find((provider) => provider.id === id);
    assert.ok(row && row.configured && row.kind === "local" && row.requires_opt_in === false);
    assert.ok(row.models.includes(PROTOCOL.model));
    return { id, configured: true, kind: "local", requires_opt_in: false, has_exact_public_qwen3_8b: true };
  });
}

export async function inspectControls(page, capture, check, width) {
  for (const provider of PROTOCOL.providers) {
    await page.getByRole("button", { name: "New rollout", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "New rollout", exact: true });
    const worker = dialog.getByLabel("Concurrency", { exact: true });
    const evaluation = dialog.getByRole("checkbox", { name: "Evaluation-only batch (excluded from training exports)", exact: true });
    assert.equal(await worker.inputValue(), "4");
    assert.equal(await evaluation.isEnabled(), true);
    assert.equal(await evaluation.isChecked(), false);
    await dialog.getByLabel("Provider", { exact: true }).selectOption(provider);
    assert.equal(await worker.inputValue(), "1");
    assert.equal(await worker.isEnabled(), true);
    assert.equal(await evaluation.isChecked(), true);
    assert.equal(await evaluation.isDisabled(), true);
    assert.equal(await dialog.getByLabel("Model", { exact: true }).inputValue(), PROTOCOL.model);
    assert.equal(await dialog.locator(".paid-consent").count(), 0);
    check(`${width}: ${provider} defaults to one worker with locked evaluation and public local model`);
    await capture(`${width}-${provider}-defaults.png`);
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    assert.equal(await dialog.isVisible(), false);
  }
  await page.getByRole("button", { name: "New rollout", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New rollout", exact: true });
  await dialog.getByLabel("Provider", { exact: true }).selectOption("local-tools");
  await dialog.getByLabel("Concurrency", { exact: true }).fill("2");
  await dialog.getByLabel("Provider", { exact: true }).selectOption("local-tools-ledger");
  assert.equal(await dialog.getByLabel("Concurrency", { exact: true }).inputValue(), "2");
  check(`${width}: explicit two workers persist between native protocols`);
  await capture(`${width}-native-explicit-two.png`);
  await dialog.getByLabel("Provider", { exact: true }).selectOption("local");
  const evaluation = dialog.getByRole("checkbox", { name: "Evaluation-only batch (excluded from training exports)", exact: true });
  assert.equal(await evaluation.isEnabled(), true);
  await evaluation.uncheck();
  await dialog.getByLabel("Concurrency", { exact: true }).fill("3");
  assert.equal(await evaluation.isChecked(), false);
  assert.equal(await dialog.getByLabel("Concurrency", { exact: true }).inputValue(), "3");
  check(`${width}: legacy local controls remain editable`);
  await capture(`${width}-legacy-editable.png`);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  assert.equal(await dialog.isVisible(), false);
}

export async function collect(options) {
  const started = Date.now();
  await reserveFreshOutput(options.output);
  const baseURL = localOrigin(process.env.WORLD_ENGINE_UI_URL ?? "http://127.0.0.1:5173");
  const source = await sourceIdentity(options.revision);
  const temporary = await mkdtemp(path.join(os.tmpdir(), "world-engine-controls-video-"));
  const report = { schema: "world-engine.native-controls-qa.v1", generated_at: new Date().toISOString(),
    plan: plan(), source, api_startup_revision_declared: options.apiStartupRevision,
    api_source_attestation: "operator-declared startup revision, not proven by health package version or remote attestation",
    checks: [], browser_errors: [], blocked_requests: [], requests: { GET: 0 }, get_paths: {},
    api_mutations: 0, new_rollouts: 0, downloads: 0, imports: 0, inference_requests: 0, suppressed_websockets: 0,
    scope: "configuration inspection only; not a native rollout, historical receipt inspection, performance result or model execution proof",
    video_cap_scope: "published artifact cap; transient Playwright video is size-checked after close, not a hard recording disk quota",
    deadline_scope: "cooperative trusted browser operations and finalization; not hard preemption" };
  let browser, context, page, videoPath, work, stopped = false;
  const remaining = () => workTimeLeft(started);
  const check = (value) => report.checks.push(value);
  try {
    const { chromium } = require("playwright");
    browser = await chromium.launch({ timeout: Math.min(15000, remaining()) });
    context = await browser.newContext({ baseURL, viewport: PROTOCOL.viewports[0], serviceWorkers: "block",
      recordVideo: { dir: temporary, size: PROTOCOL.viewports[0] } });
    context.setDefaultTimeout(5000);
    await context.route("**/*", readOnlyRoute(baseURL, report));
    await context.routeWebSocket("**/*", (socket) => {
      report.suppressed_websockets += 1;
      socket.close();
    });
    page = await context.newPage();
    page.on("pageerror", () => report.browser_errors.push("browser runtime error; details redacted"));
    page.on("response", (response) => {
      if (response.status() >= 300 && response.status() < 400)
        report.browser_errors.push("redirect response forbidden");
    });
    const capture = async (name) => {
      remaining();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      const dialog = await page.getByRole("dialog", { name: "New rollout", exact: true }).boundingBox();
      assert.ok(dialog && dialog.x >= 0 && dialog.x + dialog.width <= page.viewportSize().width + 1);
      assert.ok(dialog.y >= 0 && dialog.y + dialog.height <= page.viewportSize().height + 1);
      const bytes = await page.screenshot({ fullPage: false });
      remaining();
      await writeBounded(options.output, name, bytes);
    };
    let timer;
    try {
      work = (async () => {
        const healthResponse = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/health");
        const providerResponse = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/providers");
        await page.goto(baseURL, { timeout: Math.min(15000, remaining()) });
        const health = await healthResponse, providers = await providerResponse;
        assert.equal(health.status(), 200); assert.equal(providers.status(), 200);
        const healthValue = await health.json();
        report.native_catalog = checkMetadata(healthValue, await providers.json());
        report.api_health = { status: healthValue.status, version: healthValue.version,
          active_runs: healthValue.active_runs, paid_calls_enabled: healthValue.paid_calls_enabled };
        check("Health package version and available native local catalog match the declared public fixture");
        for (const viewport of PROTOCOL.viewports) {
          remaining();
          await page.setViewportSize(viewport);
          await inspectControls(page, capture, check, viewport.width);
        }
        assert.deepEqual(report.browser_errors, []);
        assert.deepEqual(report.blocked_requests, []);
        check("No mutation, redirect, nonlocal request or browser error during configuration inspection");
      })();
      await Promise.race([work, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Controls QA work deadline reached")), remaining());
      })]);
    } finally {
      clearTimeout(timer);
    }
    videoPath = await page.video().path();
  } catch {
    stopped = true;
    report.stop_reason = "Controls QA failed; supplied values, browser and subprocess details redacted";
  } finally {
    try {
      videoPath ??= await page?.video()?.path();
      try { await context?.close(); }
      finally { await browser?.close(); }
      report.browser_cleanup = "completed";
      if (videoPath) {
        await publishVideo(options.output, videoPath);
        report.video = "controls.webm";
      }
    } catch {
      stopped = true;
      report.browser_cleanup ??= "unconfirmed";
      report.stop_reason ??= "Browser finalization or bounded video publication failed; available evidence retained";
    }
    await work?.catch(() => {});
    await rm(temporary, { recursive: true, force: true });
    try {
      report.source_post = await sourceIdentity(options.revision);
      assert.deepEqual(report.source_post.files, source.files);
      check("Source scope remained pinned through finalization");
    } catch {
      stopped = true;
      report.stop_reason ??= "Final source gate failed; existing configuration evidence retained";
    }
    if (report.blocked_requests.length || report.browser_errors.length) {
      stopped = true;
      report.stop_reason ??= "A forbidden request or browser error was observed; available evidence retained";
    }
    report.artifact_files = {};
    for (const name of (await readdir(options.output)).sort()) {
      const bytes = await readFile(path.join(options.output, name));
      report.artifact_files[name] = { bytes: bytes.length, sha256: sha256(bytes) };
    }
    report.elapsed_seconds = (Date.now() - started) / 1000;
    if (report.elapsed_seconds > OVERALL_MS / 1000) {
      stopped = true; report.stop_reason ??= "Cooperative overall deadline exceeded";
    }
    report.status = stopped ? "stopped" : "completed";
    report.artifacts_bytes_before_report = await artifactBytes(options.output);
    report.report_bytes = 0;
    let bytes = Buffer.alloc(0);
    while (!bytes.length || report.report_bytes !== bytes.length) {
      report.report_bytes = bytes.length;
      report.artifact_total_bytes = report.artifacts_bytes_before_report + bytes.length;
      bytes = Buffer.from(JSON.stringify(report, null, 2) + "\n");
    }
    if (bytes.length > REPORT_RESERVE) throw new Error("Controls QA report exceeds reserved bytes");
    await writeBounded(options.output, "report.json", bytes, 0);
  }
  return report;
}

export async function main(args = process.argv.slice(2)) {
  const options = parseOptions(args);
  if (!options.collect) { console.log(JSON.stringify(plan(), null, 2)); return 0; }
  const report = await collect(options);
  console.log(JSON.stringify({ status: report.status, checks: report.checks.length, new_rollouts: 0, inference_requests: 0 }));
  return report.status === "completed" ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = await main(); }
  catch { console.error("Controls QA preflight/finalization failed; supplied values and subprocess details redacted"); process.exitCode = 1; }
}
