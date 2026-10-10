import assert from "node:assert/strict";
import { mkdir, readFile, readdir, unlink, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
const { chromium } = require("playwright");
const baseURL = process.env.WORLD_ENGINE_UI_URL ?? "http://127.0.0.1:5173";
const output = path.join(root, "artifacts/qa");
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  baseURL,
  viewport: { width: 1440, height: 960 },
  recordVideo: {
    dir: path.join(output, "video"),
    size: { width: 1440, height: 960 },
  },
  permissions: ["clipboard-read", "clipboard-write"],
});
const page = await context.newPage();
const errors = [];
const checks = [];
const downloads = [];
const contrastResults = [];
let completedReport;
page.on("pageerror", (error) => errors.push(error.message));
const check = (name, condition) => {
  assert.ok(condition, name);
  checks.push(name);
};
const screenshot = async (name) => {
  await page
    .locator(".toast button")
    .evaluateAll((buttons) => buttons.forEach((button) => button.click()));
  await page.screenshot({
    path: path.join(output, name),
    fullPage: !name.startsWith("mobile-"),
  });
};
const withinViewport = async (name) =>
  check(
    `${name}: document has no horizontal overflow`,
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  );
const checkTextContrast = async (name) => {
  const samples = await page.evaluate(() => {
    const channels = (value) =>
      value
        .match(/[\d.]+/g)
        ?.slice(0, 3)
        .map(Number) ?? [0, 0, 0];
    const luminance = (value) =>
      channels(value)
        .map((channel) => {
          const scaled = channel / 255;
          return scaled <= 0.04045
            ? scaled / 12.92
            : ((scaled + 0.055) / 1.055) ** 2.4;
        })
        .reduce(
          (total, channel, index) =>
            total + channel * [0.2126, 0.7152, 0.0722][index],
          0,
        );
    return Array.from(
      document.querySelectorAll(
        ".metric > span, .metric small, .text-muted, th, .eyebrow, .episode-item small, .trace-item small, .grader-check p, .field-note, .dialog-body label",
      ),
    )
      .filter((element) => element.getBoundingClientRect().height > 0)
      .map((element) => {
        const foreground = getComputedStyle(element).color;
        let parent = element;
        let background = "rgb(255, 255, 255)";
        while (parent) {
          const candidate = getComputedStyle(parent).backgroundColor;
          if (candidate !== "rgba(0, 0, 0, 0)" && candidate !== "transparent") {
            background = candidate;
            break;
          }
          parent = parent.parentElement;
        }
        const first = luminance(foreground),
          second = luminance(background);
        return {
          text: element.textContent?.trim().slice(0, 60),
          ratio:
            (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05),
        };
      });
  });
  check(
    `${name}: sampled small labels meet 4.5:1 text contrast`,
    samples.length > 0 && samples.every((sample) => sample.ratio >= 4.5),
  );
  contrastResults.push({
    view: name,
    samples: samples.length,
    minimum_ratio: Math.min(...samples.map((sample) => sample.ratio)),
  });
};

try {
  const health = await context.request.get("/api/health");
  check("API health responds through the Vite proxy", health.ok());
  const providerResponse = await context.request.get("/api/providers");
  const { providers } = await providerResponse.json();
  const worldResponse = await context.request.get("/api/environments");
  const { environments } = await worldResponse.json();
  check(
    "Real environment registry contains workflow worlds",
    environments.length >= 3,
  );
  await page.goto("/#runs");
  await page.getByText("Runtime connected", { exact: true }).waitFor();
  await page.getByRole("button", { name: "New rollout", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New rollout" });
  await dialog.waitFor();
  check(
    "Rollout dialog receives keyboard focus",
    await dialog
      .getByLabel("Run label")
      .evaluate((element) => element === document.activeElement),
  );
  await dialog.getByLabel("Run label").fill("QA / CRM oracle");
  await dialog
    .getByLabel("Environment", { exact: true })
    .selectOption("crm-merge");
  await dialog
    .getByLabel("Provider", { exact: true })
    .selectOption("scripted-oracle");
  await dialog.getByLabel("Episodes", { exact: true }).fill("0");
  check(
    "Episode lower bound rejects zero",
    !(await dialog
      .getByLabel("Episodes", { exact: true })
      .evaluate((element) => element.checkValidity())),
  );
  await dialog.getByLabel("Episodes", { exact: true }).fill("101");
  check(
    "Episode upper bound rejects 101",
    !(await dialog
      .getByLabel("Episodes", { exact: true })
      .evaluate((element) => element.checkValidity())),
  );
  await dialog.getByLabel("Episodes", { exact: true }).fill("8");
  await dialog.getByLabel("Concurrency", { exact: true }).fill("9");
  check(
    "Concurrency upper bound rejects 9",
    !(await dialog
      .getByLabel("Concurrency", { exact: true })
      .evaluate((element) => element.checkValidity())),
  );
  await dialog.getByLabel("Concurrency", { exact: true }).fill("2");
  await dialog.getByLabel("Max steps / episode").fill("20");
  await dialog.getByLabel("Starting seed").fill("730");
  await screenshot("desktop-new-rollout.png");
  await checkTextContrast("New rollout");
  const createResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Start rollout", exact: true })
    .click();
  const created = await (await createResponse).json();
  check(
    "UI submits the actual run configuration",
    created.config.seed === 730 &&
      created.config.episodes === 8 &&
      created.config.allow_paid === false,
  );
  await page.waitForURL(`**/#runs/${created.id}`);
  await page
    .getByRole("heading", { name: "QA / CRM oracle", exact: true })
    .waitFor();
  await page.getByText("Hidden grader", { exact: true }).waitFor();
  await page.locator(".detail-subtitle .status-completed").waitFor();
  const detailResponse = await context.request.get(`/api/runs/${created.id}`);
  const detail = await detailResponse.json();
  check(
    "Created run records real episode traces",
    detail.episodes.length > 0 && detail.episodes[0].trace.length > 0,
  );
  check(
    "Episode has hidden grading and state provenance",
    detail.episodes[0].grader.checks.length > 0 &&
      Boolean(detail.episodes[0].final_state_hash),
  );
  await withinViewport("Desktop inspector");
  await checkTextContrast("Run inspector");
  await screenshot("desktop-run-detail.png");
  const traceButtons = page.locator(".trace-item");
  if ((await traceButtons.count()) > 1) {
    await traceButtons.nth(1).click();
    check(
      "Timeline changes the selected action",
      await page
        .locator(".step-heading")
        .innerText()
        .then((text) => text.includes("Step 2")),
    );
  }
  await page
    .getByRole("button", { name: "Copy action JSON", exact: true })
    .click();
  await page.getByText("Copied to clipboard.", { exact: true }).waitFor();
  check(
    "Copy action writes actual JSON",
    JSON.parse(await page.evaluate(() => navigator.clipboard.readText()))
      .tool === detail.episodes[0].trace[1]?.action.tool ||
      detail.episodes[0].trace.length === 1,
  );
  await page.goto("/#runs");
  await page.getByRole("button", { name: "New rollout", exact: true }).click();
  const baselineDialog = page.getByRole("dialog", { name: "New rollout" });
  await baselineDialog.getByLabel("Run label").fill("QA / CRM baseline");
  await baselineDialog
    .getByLabel("Environment", { exact: true })
    .selectOption("crm-merge");
  await baselineDialog
    .getByLabel("Provider", { exact: true })
    .selectOption("scripted-baseline");
  await baselineDialog.getByLabel("Episodes", { exact: true }).fill("8");
  await baselineDialog.getByLabel("Starting seed").fill("730");
  const baselinePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await baselineDialog
    .getByRole("button", { name: "Start rollout", exact: true })
    .click();
  const baseline = await (await baselinePromise).json();
  await page.waitForURL(`**/#runs/${baseline.id}`);
  await page.locator(".detail-subtitle .status-completed").waitFor();
  await page.goto(`/#runs/${created.id}`);
  await page.getByText("Hidden grader", { exact: true }).waitFor();
  for (const format of ["traces", "sft", "dpo", "grpo"]) {
    await page.getByLabel("Export format").selectOption(format);
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const download = await downloadPromise;
    const target = path.join(output, download.suggestedFilename());
    await download.saveAs(target);
    const content = await readFile(target, "utf8");
    const lines = content.trim() ? content.trim().split("\n") : [];
    for (const line of lines) JSON.parse(line);
    if (format === "traces")
      check("Raw trace export contains recorded episodes", lines.length > 0);
    if (format === "dpo" || format === "grpo")
      check(
        `${format.toUpperCase()} export contains real matched alternatives`,
        lines.length > 0,
      );
    downloads.push({
      format,
      rows: lines.length,
      filename: download.suggestedFilename(),
    });
  }
  checks.push("All four export formats download valid JSONL");
  await page.getByRole("tab", { name: "Provenance", exact: true }).click();
  await page.getByRole("heading", { name: "Episode provenance" }).waitFor();
  check(
    "Provenance displays episode seeds and final hashes",
    await page
      .getByText(detail.episodes[0].final_state_hash, { exact: true })
      .isVisible(),
  );
  await screenshot("desktop-provenance.png");
  await page.locator(".frozen-provenance summary").first().click();
  const frozen = await page
    .locator(".frozen-provenance details[open] pre")
    .innerText();
  check(
    "Frozen provenance preserves implementation hashes and lineage",
    frozen.includes(detail.episodes[0].provenance.environment_code_hash) &&
      frozen.includes(detail.episodes[0].provenance.lineage_id),
  );
  check(
    "Episode termination and usage are retained",
    frozen.includes("finished") && frozen.includes("input_tokens"),
  );
  await screenshot("desktop-frozen-provenance.png");
  await page.getByRole("link", { name: "Rollout runs", exact: true }).click();
  await page.locator(`a[href="#runs/${created.id}"]`).first().waitFor();
  await screenshot("desktop-runs.png");
  await page.getByLabel("Search runs").fill("this-query-has-no-result");
  check(
    "Run search has a working empty state",
    await page.getByRole("heading", { name: "No matching runs" }).isVisible(),
  );
  await page.getByLabel("Search runs").fill("");
  await page.getByRole("link", { name: "World library", exact: true }).click();
  await page.getByRole("heading", { name: "Action tools" }).waitFor();
  await page.locator(".tool-list summary").first().click();
  check(
    "World library exposes real action schemas",
    await page.locator(".tool-list details[open] pre").isVisible(),
  );
  await screenshot("desktop-worlds.png");
  await page.getByRole("link", { name: "Benchmarks", exact: true }).click();
  await page.getByRole("heading", { name: "Success by run" }).waitFor();
  await page
    .locator("tr")
    .filter({ has: page.locator(`a[href="#runs/${created.id}"]`) })
    .getByRole("checkbox")
    .check();
  await page
    .locator("tr")
    .filter({ has: page.locator(`a[href="#runs/${baseline.id}"]`) })
    .getByRole("checkbox")
    .check();
  check(
    "Comparison uses selected real runs",
    await page.getByText("2 selected", { exact: true }).isVisible(),
  );
  await screenshot("desktop-benchmarks.png");
  await page.getByRole("link", { name: "Runtime", exact: true }).click();
  await page
    .getByRole("heading", { name: "Local runtime", exact: true })
    .waitFor();
  check(
    "Runtime does not expose credential inputs",
    (await page.locator("input[type=password]").count()) === 0,
  );
  await screenshot("desktop-runtime.png");

  const remote = providers.find((provider) => provider.requires_opt_in);
  if (remote) {
    const denied = await context.request.post("/api/runs", {
      data: {
        ...created.config,
        provider_id: remote.id,
        allow_paid: false,
        episodes: 1,
      },
    });
    check(
      "Remote provider rejects calls without explicit paid consent",
      !denied.ok(),
    );
  }
  const local = providers.find(
    (provider) => provider.id === "local" && provider.configured,
  );
  if (local) {
    await page.getByRole("link", { name: "Rollout runs", exact: true }).click();
    await page
      .getByRole("button", { name: "New rollout", exact: true })
      .click();
    const cancellationDialog = page.getByRole("dialog", {
      name: "New rollout",
    });
    await cancellationDialog.getByLabel("Run label").fill("QA / cancellation");
    await cancellationDialog
      .getByLabel("Provider", { exact: true })
      .selectOption("local");
    await cancellationDialog
      .getByLabel("Episodes", { exact: true })
      .fill("100");
    await cancellationDialog
      .getByLabel("Concurrency", { exact: true })
      .fill("1");
    await cancellationDialog.getByLabel("Timeout / episode (s)").fill("5");
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/runs") &&
        response.request().method() === "POST",
    );
    await cancellationDialog
      .getByRole("button", { name: "Start rollout", exact: true })
      .click();
    const cancellationRun = await (await responsePromise).json();
    await page
      .getByRole("button", { name: "Cancel run", exact: true })
      .waitFor();
    await screenshot("desktop-live-job.png");
    await page.getByRole("button", { name: "Cancel run", exact: true }).click();
    await page.locator(".detail-subtitle .status-cancelled").waitFor();
    const final = await context.request.get(`/api/runs/${cancellationRun.id}`);
    check(
      "Live local job cancels through the UI",
      (await final.json()).status === "cancelled",
    );
  } else checks.push("Local cancellation not exercised: provider unavailable");

  await page.setViewportSize({ width: 390, height: 844 });
  for (const view of ["runs", "worlds", "benchmarks", "runtime"]) {
    await page.goto(`/#${view}`);
    await page.getByRole("heading", { level: 1 }).waitFor();
    await withinViewport(`Mobile ${view}`);
    await screenshot(`mobile-${view}.png`);
  }
  await page.goto(`/#runs/${created.id}`);
  await page.getByText("Hidden grader", { exact: true }).waitFor();
  await withinViewport("Mobile inspector");
  await screenshot("mobile-run-detail.png");
  await page.locator(".trace-layout").scrollIntoViewIfNeeded();
  await screenshot("mobile-trace-step.png");
  await page.locator(".grader-section").scrollIntoViewIfNeeded();
  await screenshot("mobile-grader.png");
  await page.goto("/#runs");
  await page.getByRole("button", { name: "New rollout", exact: true }).click();
  await withinViewport("Mobile new rollout");
  await screenshot("mobile-new-rollout.png");
  await page.keyboard.press("Escape");
  check(
    "Escape closes the accessible rollout dialog",
    !(await page.getByRole("dialog").isVisible()),
  );
  check("No browser runtime errors", errors.length === 0);
  completedReport = { downloads, video: await page.video().path() };
  await writeFile(
    path.join(output, "ui-report.json"),
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        base_url: baseURL,
        run_id: created.id,
        baseline_run_id: baseline.id,
        checks,
        downloads,
        text_contrast: contrastResults,
        browser_errors: errors,
        real_episode_count: detail.episodes.length,
        real_trace_steps: detail.episodes.reduce(
          (total, episode) => total + episode.trace.length,
          0,
        ),
        video: await page.video().path(),
      },
      null,
      2,
    ),
  );
  console.log(
    `UI QA passed: ${checks.length} checks, run ${created.id}, ${detail.episodes.length} episodes. Screenshots, exports, and video: ${output}`,
  );
} finally {
  await context.close();
  await browser.close();
}

if (completedReport) {
  const currentDownloads = new Set(
    completedReport.downloads.map((item) => item.filename),
  );
  for (const name of await readdir(output)) {
    if (name.endsWith(".jsonl") && !currentDownloads.has(name))
      await unlink(path.join(output, name));
  }
  for (const name of await readdir(path.join(output, "video"))) {
    const file = path.join(output, "video", name);
    if (name.endsWith(".webm") && file !== completedReport.video)
      await unlink(file);
  }
}
