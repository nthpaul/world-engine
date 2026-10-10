import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { reserveFreshOutput } from "./ui-qa.mjs";
import { localBaseURL } from "./native-ui-qa.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
export const ARTIFACT_CAP = 64 * 1024 ** 2;
export const OVERALL_MS = 120000;
const RESERVE = 1024 ** 2;
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const scope = [
  "src/world_engine",
  "web/src",
  "web/package.json",
  "web/package-lock.json",
  "web/vite.config.ts",
  "web/index.html",
  "pyproject.toml",
  "uv.lock",
  "scripts/browser-console-qa.mjs",
  "scripts/ui-browser-check.mjs",
  "scripts/ui-qa.mjs",
  "scripts/native-ui-qa.mjs",
  "tests/test_ui_browser_console.py",
];

export function plan() {
  return {
    mode: "read-only browser console inspection",
    viewports: [1440, 390, 360],
    new_attempts: 0,
    inference_calls: 0,
    allowed_methods: ["GET"],
    artifact_cap_bytes: ARTIFACT_CAP,
    overall_ms: OVERALL_MS,
    limits:
      "Cooperative deadline and post-close video quota check, not a hard video filesystem quota.",
    status: "plan only / no browser, API, source commands or output",
  };
}
export function parseOptions(args) {
  try {
    const { values } = parseArgs({
      args,
      strict: true,
      allowPositionals: false,
      options: {
        collect: { type: "boolean" },
        plan: { type: "boolean" },
        "attempt-id": { type: "string" },
        "source-revision": { type: "string" },
        "api-startup-revision": { type: "string" },
        output: { type: "string" },
      },
    });
    if (!values.collect) {
      if (
        values["attempt-id"] ||
        values["source-revision"] ||
        values.output ||
        values["api-startup-revision"]
      )
        throw new Error();
      return { collect: false };
    }
    if (
      values.plan ||
      !/^[a-f0-9-]{36}$/.test(values["attempt-id"] ?? "") ||
      !/^[a-f0-9]{40}$/.test(values["source-revision"] ?? "") ||
      !values.output?.trim() ||
      (values["api-startup-revision"] &&
        !/^[a-f0-9]{40}$/.test(values["api-startup-revision"]))
    )
      throw new Error();
    return {
      collect: true,
      attemptId: values["attempt-id"],
      revision: values["source-revision"],
      apiStartupRevision: values["api-startup-revision"] ?? null,
      output: path.resolve(values.output),
    };
  } catch {
    throw new Error(
      "Use --plan or --collect with --attempt-id, reviewed full --source-revision and fresh --output; values redacted",
    );
  }
}
export function allowedRequest(baseURL, method, value, redirected = false) {
  try {
    const url = new URL(value);
    const apiAllowed =
      [
        "/api/health",
        "/api/environments",
        "/api/providers",
        "/api/runs",
        "/api/browser/tasks",
        "/api/browser/status",
        "/api/browser/attempts",
      ].includes(url.pathname) ||
      /^\/api\/browser\/attempts\/[a-f0-9-]{36}(?:\/artifacts\/[A-Za-z0-9._%/-]+)?$/.test(
        url.pathname,
      );
    return (
      method === "GET" &&
      !redirected &&
      url.origin === baseURL &&
      !url.username &&
      !url.password &&
      (!url.pathname.startsWith("/api/") || apiAllowed)
    );
  } catch {
    return false;
  }
}
export function readOnlyRoute(baseURL, report) {
  return async (route) => {
    const request = route.request();
    if (
      !allowedRequest(
        baseURL,
        request.method(),
        request.url(),
        Boolean(request.redirectedFrom()),
      )
    ) {
      report.blocked_requests.push({
        method: request.method(),
        redirected: Boolean(request.redirectedFrom()),
      });
      await route.abort();
      return;
    }
    report.get_requests += 1;
    try {
      const response = await route.fetch({ maxRedirects: 0, timeout: 15000 });
      if (
        (response.status() >= 300 && response.status() < 400) ||
        new URL(response.url()).origin !== baseURL
      ) {
        report.blocked_requests.push({ method: "GET", redirected: true });
        await route.abort();
        return;
      }
      await route.fulfill({ response });
    } catch {
      report.browser_errors.push("Read-only GET failed; details redacted");
      await route.abort();
    }
  };
}
export async function sourceIdentity(expected) {
  try {
    const git = (args) =>
      execFileSync("git", ["-C", root, ...args], {
        encoding: "utf8",
        timeout: 5000,
      }).trim();
    if (
      git(["rev-parse", "HEAD"]) !== expected ||
      git(["status", "--porcelain", "--untracked-files=all", "--", ...scope])
    )
      throw new Error();
    const files = {};
    for (const name of scope) {
      const info = await lstat(path.join(root, name));
      const names = info.isDirectory()
        ? (await readdir(path.join(root, name), { recursive: true }))
            .map((entry) => path.join(name, entry))
            .sort()
        : [name];
      for (const entry of names) {
        const stat = await lstat(path.join(root, entry));
        if (stat.isSymbolicLink()) throw new Error();
        if (
          stat.isFile() &&
          !entry.includes("__pycache__") &&
          !entry.endsWith(".pyc")
        )
          files[entry] = sha256(await readFile(path.join(root, entry)));
      }
    }
    return {
      revision: expected,
      source_dirty: false,
      checkout_dirty: Boolean(
        git(["status", "--porcelain", "--untracked-files=all"]),
      ),
      files,
    };
  } catch {
    throw new Error(
      "Browser console QA requires the reviewed committed clean source scope; details redacted",
    );
  }
}
export async function artifactBytes(directory) {
  let total = 0;
  for (const entry of await readdir(directory, { recursive: true })) {
    const stat = await lstat(path.join(directory, entry));
    if (stat.isSymbolicLink()) throw new Error("QA output contains a symlink");
    if (stat.isFile()) total += stat.size;
  }
  return total;
}
export async function writeBounded(directory, name, bytes, reserve = RESERVE) {
  if (
    !/^[A-Za-z0-9._-]+$/.test(name) ||
    (await artifactBytes(directory)) + bytes.length + reserve > ARTIFACT_CAP
  )
    throw new Error("Browser console QA artifact budget exceeded");
  await writeFile(path.join(directory, name), bytes, {
    flag: "wx",
    mode: 0o600,
  });
}
export async function collect(options) {
  await reserveFreshOutput(options.output);
  const baseURL = localBaseURL(
    process.env.WORLD_ENGINE_UI_URL ?? "http://127.0.0.1:5173",
  );
  const source = await sourceIdentity(options.revision);
  const report = {
    generated_at: new Date().toISOString(),
    plan: plan(),
    source,
    api_startup_revision_operator_attestation: options.apiStartupRevision,
    attempt_id: options.attemptId,
    status: "inconclusive",
    checks: [],
    get_requests: 0,
    blocked_requests: [],
    browser_errors: [],
    artifacts: [],
    screenshots: [],
    inference_calls: 0,
    new_attempts: 0,
    limits: plan().limits,
  };
  const started = Date.now();
  let browser;
  let context;
  let videoPath;
  let server;
  const remaining = () => {
    const value = OVERALL_MS - (Date.now() - started) - 15000;
    if (value <= 0) throw new Error("Browser console QA deadline reached");
    return value;
  };
  const check = (name, value) => {
    assert.ok(value, name);
    report.checks.push({ name, passed: true });
  };
  try {
    const viteRoot = path.dirname(require.resolve("vite/package.json"));
    const { createServer } = await import(
      pathToFileURL(path.join(viteRoot, "dist/node/index.js")).href
    );
    server = await createServer({
      root: path.join(root, "web"),
      configFile: false,
      logLevel: "silent",
      server: { middlewareMode: true, watch: null },
      optimizeDeps: { noDiscovery: true, include: [] },
    });
    const { browserDetailSchema, browserStatusSchema } =
      await server.ssrLoadModule("/src/browserApi.ts");
    const { chromium } = require("playwright");
    browser = await chromium.launch({ headless: true });
    const videoDirectory = path.join(options.output, "video");
    await mkdir(videoDirectory);
    context = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      recordVideo: { dir: videoDirectory, size: { width: 1440, height: 960 } },
      serviceWorkers: "block",
    });
    await context.route("**/*", readOnlyRoute(baseURL, report));
    const get = async (pathname, limit) => {
      if (!allowedRequest(baseURL, "GET", baseURL + pathname))
        throw new Error("Unsafe read-only request");
      report.get_requests += 1;
      const response = await context.request.get(baseURL + pathname, {
        maxRedirects: 0,
        timeout: Math.min(15000, remaining()),
      });
      if (!response.ok() || new URL(response.url()).origin !== baseURL)
        throw new Error("Browser API GET failed; details redacted");
      if (
        ![undefined, "identity"].includes(
          response.headers()["content-encoding"],
        )
      )
        throw new Error("Encoded API evidence is not accepted");
      const bytes = await response.body();
      if (bytes.length > limit)
        throw new Error("Browser API response exceeds QA bound");
      return bytes;
    };
    const health = JSON.parse(await get("/api/health", 64 * 1024));
    check("Paid server gate disabled", health.paid_calls_enabled === false);
    const runtime = browserStatusSchema.parse(
      JSON.parse(await get("/api/browser/status", 64 * 1024)),
    );
    report.runtime = {
      package_version: health.version,
      package_version_is_not_source_revision: true,
      active_simulation_runs: health.active_runs,
      browser_available: runtime.available,
      active_attempts: runtime.active_attempts,
      max_active_attempts: runtime.max_active_attempts,
      paid_calls_enabled: runtime.paid_calls_enabled,
    };
    const raw = await get(
      `/api/browser/attempts/${options.attemptId}`,
      16 * 1024 ** 2,
    );
    await writeBounded(options.output, "attempt.json", raw);
    const detail = browserDetailSchema.parse(JSON.parse(raw));
    check("Requested attempt identity", detail.id === options.attemptId);
    check("Evaluation-only task", detail.task.evaluation_only === true);
    report.attempt = {
      id: detail.id,
      status: detail.status,
      termination: detail.termination,
      provider_id: detail.config.provider_id,
      seed: detail.config.seed,
      steps: detail.steps,
      invalid_actions: detail.invalid_actions,
      passed: detail.passed,
      reward: detail.reward,
      outcome: detail.outcome,
      cleanup: detail.cleanup,
      schema: detail.schema,
      observation_mode: detail.task.observation_mode,
      detail_sha256: sha256(raw),
      detail_bytes: raw.length,
    };
    for (const [index, artifact] of detail.artifacts.entries()) {
      if (
        artifact.size_bytes + (await artifactBytes(options.output)) + RESERVE >
        ARTIFACT_CAP
      )
        throw new Error("Recorded artifact exceeds remaining QA budget");
      const bytes = await get(artifact.url, artifact.size_bytes + 1);
      check(
        `Artifact ${index} byte size and digest`,
        bytes.length === artifact.size_bytes &&
          sha256(bytes) === artifact.sha256,
      );
      const extension =
        artifact.kind === "video"
          ? "webm"
          : artifact.kind === "public_trace"
            ? "jsonl"
            : artifact.mime_type === "image/jpeg"
              ? "jpg"
              : "png";
      const name = `recorded-${String(index).padStart(3, "0")}-${artifact.kind}.${extension}`;
      await writeBounded(options.output, name, bytes);
      report.artifacts.push({ ...artifact, saved_file: name });
    }
    const page = await context.newPage();
    videoPath = await page.video().path();
    page.on("pageerror", () =>
      report.browser_errors.push("Browser application error; details redacted"),
    );
    page.on("console", (message) => {
      if (message.type() === "error")
        report.browser_errors.push("Browser console error; details redacted");
    });
    page.setDefaultTimeout(10000);
    await page.goto(
      `${baseURL}/#attempts/${encodeURIComponent(options.attemptId)}`,
      { timeout: remaining() },
    );
    await page.getByRole("tab", { name: "Browser", exact: true }).waitFor();
    check(
      "Actual browser attempt heading",
      await page
        .getByRole("heading", { name: detail.task.name, exact: true })
        .isVisible(),
    );
    const capture = async (name) => {
      remaining();
      const dimensions = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      check(
        `${name} no body horizontal overflow`,
        dimensions.width <= dimensions.viewport + 1,
      );
      await writeBounded(
        options.output,
        `${name}.png`,
        await page.screenshot({ fullPage: true }),
      );
      report.screenshots.push(`${name}.png`);
    };
    for (const width of [1440, 390, 360]) {
      await page.setViewportSize({ width, height: width === 1440 ? 960 : 844 });
      for (const tab of ["Browser", "Timeline", "Outcome"]) {
        await page.getByRole("tab", { name: tab, exact: true }).click();
        if (
          tab === "Timeline" &&
          detail.journal.some((entry) => entry.event === "action_result")
        ) {
          await page
            .getByRole("button", { name: /action result/ })
            .first()
            .click();
          check(
            `${width} recorded action result inspected`,
            await page
              .getByRole("heading", {
                name: "Recorded event / action result",
                exact: true,
              })
              .isVisible(),
          );
        }
        if (tab === "Browser") {
          const image = page.getByRole("img", {
            name: /^Captured browser screen/,
          });
          if (detail.journal.some((entry) => entry.event === "observation")) {
            await image.waitFor();
            check(
              `${width} captured image decoded`,
              await image.evaluate(
                (element) =>
                  element instanceof HTMLImageElement &&
                  element.complete &&
                  element.naturalWidth > 1,
              ),
            );
          }
        }
        await capture(`${width}-${tab.toLowerCase()}`);
      }
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Browser Environments", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Browser Environments", exact: true })
      .waitFor();
    await capture("1440-environments");
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Attempts", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Attempts", exact: true })
      .waitFor();
    await capture("1440-attempts");
    check(
      "No mutation or redirected requests",
      report.blocked_requests.length === 0,
    );
    check("No browser application errors", report.browser_errors.length === 0);
    videoPath = await page.video().path();
    report.status = "passed";
  } catch {
    report.status = "inconclusive";
    report.error =
      "Read-only browser console inspection failed; details redacted, evidence prefix preserved";
  } finally {
    for (const resource of [context, browser, server]) {
      try {
        await resource?.close();
      } catch {
        report.status = "inconclusive";
        report.error = "QA resource finalization failed; details redacted";
      }
    }
    if (videoPath) {
      try {
        report.ui_video = {
          relative_path: path.relative(options.output, videoPath),
          bytes: (await lstat(videoPath)).size,
          sha256: sha256(await readFile(videoPath)),
        };
      } catch {
        report.status = "inconclusive";
        report.error = "QA video finalization incomplete";
      }
    }
    try {
      report.source_after = await sourceIdentity(options.revision);
      check(
        "Source content unchanged",
        JSON.stringify(report.source_after.files) ===
          JSON.stringify(source.files),
      );
    } catch {
      report.status = "inconclusive";
      report.error =
        "Source changed or source verification unavailable after finalization";
    }
    report.elapsed_seconds = (Date.now() - started) / 1000;
    const bytes = await artifactBytes(options.output);
    report.original_artifact_bytes_before_report = bytes;
    if (bytes + RESERVE > ARTIFACT_CAP) {
      report.status = "inconclusive";
      report.error =
        "Video finalization exceeded the cooperative QA artifact budget; originals preserved";
    }
    const encoded = Buffer.from(JSON.stringify(report, null, 2) + "\n");
    if (encoded.length > RESERVE)
      throw new Error("QA report exceeds its reserved byte budget");
    // A video quota breach must retain a truthful failure receipt, never prune evidence.
    await writeFile(path.join(options.output, "report.json"), encoded, {
      flag: "wx",
      mode: 0o600,
    });
  }
  console.log(
    JSON.stringify({
      status: report.status,
      checks: report.checks.length,
      output: options.output,
      new_attempts: 0,
      inference_calls: 0,
    }),
  );
  if (report.status !== "passed") process.exitCode = 1;
  return report;
}
export async function main(args = process.argv.slice(2)) {
  const options = parseOptions(args);
  if (!options.collect) console.log(JSON.stringify(plan(), null, 2));
  else await collect(options);
}
if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  main().catch(() => {
    console.error(
      "Browser console QA preflight failed; supplied values and subprocess details redacted",
    );
    process.exitCode = 1;
  });
