import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parseArgs } from "node:util";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export function parseOptions(args) {
  const { values } = parseArgs({ args, strict: true, allowPositionals: false,
    options: { output: { type: "string" }, atif: { type: "boolean" },
      access: { type: "boolean" }, "local-cancel": { type: "boolean" } } });
  if (!values.output?.trim()) throw new Error("An explicit fresh --output directory is required");
  if (values.atif && values.access) throw new Error("--atif and --access are mutually exclusive");
  if (values["local-cancel"] && (values.atif || values.access))
    throw new Error("--local-cancel is only permitted in the standard QA phase");
  return { output: path.resolve(values.output),
    phase: values.atif ? "atif" : values.access ? "access" : "standard",
    localCancel: values["local-cancel"] === true };
}

export async function reserveFreshOutput(output) {
  try {
    await lstat(output);
    throw new Error("QA output already exists; refusing to overwrite evidence");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  await mkdir(path.dirname(output), { recursive: true });
  await mkdir(output); // Exclusive reservation also closes the preflight existence race.
}

export function operatorEpisodeJsonl(rawDetails) {
  if (!Array.isArray(rawDetails) || !rawDetails.length ||
      rawDetails.some((value) => typeof value !== "string"))
    throw new Error("Raw API detail responses are required");
  const input = JSON.stringify(rawDetails);
  if (Buffer.byteLength(input) > 16 * 1024 * 1024)
    throw new Error("Raw API detail responses exceed the receipt budget");
  // JavaScript numbers lose authoritative float types and integers above 2^53.
  return execFileSync("uv", ["run", "python", "-c", [
    "import json, sys",
    "for raw in json.load(sys.stdin):",
    "    detail = json.loads(raw)",
    "    for episode in detail['episodes']:",
    "        print(json.dumps(episode, sort_keys=True, separators=(',', ':'), allow_nan=False))",
  ].join("\n")], { cwd: root, input, encoding: "utf8", timeout: 10000,
    maxBuffer: 16 * 1024 * 1024 });
}

async function main(options) {
const output = options.output;
await reserveFreshOutput(output);
const require = createRequire(path.join(root, "web/package.json"));
const { chromium } = require("playwright");
const baseURL = process.env.WORLD_ENGINE_UI_URL ?? "http://127.0.0.1:5173";
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

async function runAtifQA() {
  const health = await context.request.get("/api/health");
  check("Committed API responds through Vite", health.ok());
  await page.goto("/#runs");
  await page.getByText("Runtime connected", { exact: true }).waitFor();
  await page.getByRole("button", { name: "New rollout", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New rollout" });
  await dialog.getByLabel("Run label").fill("QA / ATIF evaluation-only");
  await dialog
    .getByLabel("Environment", { exact: true })
    .selectOption("crm-merge");
  await dialog
    .getByLabel("Provider", { exact: true })
    .selectOption("scripted-baseline");
  await dialog.getByLabel("Episodes", { exact: true }).fill("2");
  await dialog.getByLabel("Starting seed").fill("730");
  await dialog.getByLabel("Max steps / episode").fill("1");
  await dialog.getByLabel("Concurrency", { exact: true }).fill("1");
  await dialog
    .getByRole("checkbox", {
      name: "Evaluation-only batch (excluded from training exports)",
    })
    .check();
  await screenshot("desktop-atif-new-rollout.png");
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Start rollout", exact: true })
    .click();
  const created = await (await responsePromise).json();
  check(
    "UI creates an evaluation-only scripted batch without model calls",
    created.config.evaluation_only === true &&
      created.config.provider_id === "scripted-baseline" &&
      created.config.allow_paid === false,
  );
  await page.waitForURL(`**/#runs/${created.id}`);
  await page.locator(".detail-subtitle .status-completed").waitFor();
  const detail = await (
    await context.request.get(`/api/runs/${created.id}`)
  ).json();
  check(
    "Real failed episodes retain max-step termination",
    detail.episodes.length === 2 &&
      detail.episodes.every(
        (episode) =>
          episode.termination === "max_steps" &&
          episode.reward === 0 &&
          episode.passed === false,
      ),
  );
  await page.getByLabel("Export format").selectOption("atif");
  check(
    "Harbor ATIF selection remains active",
    (await page.getByLabel("Export format").inputValue()) === "atif",
  );
  await withinViewport("Desktop ATIF inspector");
  await checkTextContrast("ATIF inspector");
  await screenshot("desktop-atif-inspector.png");
  const downloadPromise = page.waitForEvent("download");
  const exportResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("format=atif") &&
      response.url().includes("quality=all"),
  );
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const download = await downloadPromise;
  const allFilename = `${created.id}-atif-all.jsonl`;
  const target = path.join(output, allFilename);
  await download.saveAs(target);
  const content = await readFile(target, "utf8");
  const trajectories = content
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const exportResponse = await exportResponsePromise;
  check(
    "ATIF download contains both evaluation-only episodes",
    exportResponse.ok() &&
      exportResponse.headers()["x-export-records"] === "2" &&
      trajectories.length === 2,
  );
  for (const trajectory of trajectories) {
    const episode = detail.episodes.find(
      (item) => item.id === trajectory.trajectory_id,
    );
    assert.ok(
      episode,
      "Exported trajectory references the recorded API episode",
    );
    assert.equal(trajectory.schema_version, "ATIF-v1.8");
    assert.equal(trajectory.session_id, created.id);
    assert.equal(trajectory.extra.evaluation_only, true);
    assert.equal(trajectory.extra.training_eligible, false);
    for (const key of [
      "reward",
      "passed",
      "status",
      "termination",
      "invalid_actions",
      "split",
      "lineage_id",
    ])
      assert.deepEqual(trajectory.extra.world_engine[key], episode[key]);
    assert.equal("grader" in trajectory.extra.world_engine, false);
    assert.equal("initial_snapshot" in trajectory.extra.world_engine, false);
    const decisions = trajectory.steps.filter(
      (step) => step.source === "agent",
    );
    assert.equal(decisions.length, episode.trace.length);
    decisions.forEach((step, index) => {
      const recorded = episode.trace[index];
      assert.equal(step.llm_call_count, 0);
      assert.equal("metrics" in step, false);
      assert.equal("timestamp" in step, false);
      assert.deepEqual(step.extra.policy_input, recorded.policy_input);
      assert.ok(
        step.extra.policy_input_scope.includes("not a provider transcript"),
      );
      assert.equal(step.tool_calls[0].function_name, recorded.action.tool);
      assert.deepEqual(step.tool_calls[0].arguments, recorded.action.args);
      assert.equal(
        step.observation.results[0].source_call_id,
        step.tool_calls[0].tool_call_id,
      );
      assert.deepEqual(JSON.parse(step.observation.results[0].content), {
        tool_result: recorded.result,
        observation: recorded.observation,
      });
    });
  }
  checks.push(
    "Native ATIF fields preserve actions, observations, controller context, outcome and evaluation exclusion",
  );
  checks.push(
    "Scripted ATIF decisions do not fabricate model metrics or timestamps",
  );
  downloads.push({
    format: "atif",
    quality: "all",
    rows: trajectories.length,
    filename: allFilename,
    suggested_filename: download.suggestedFilename(),
    sha256: createHash("sha256").update(content).digest("hex"),
  });
  await page.getByLabel("Export quality").selectOption("passed");
  const emptyPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const empty = await emptyPromise;
  const passedFilename = `${created.id}-atif-passed.jsonl`;
  const emptyTarget = path.join(output, passedFilename);
  await empty.saveAs(emptyTarget);
  check(
    "Passed-only ATIF excludes both unsuccessful episodes",
    (await readFile(emptyTarget, "utf8")).trim() === "",
  );
  check(
    "Quality-specific download paths preserve the full ATIF artifact",
    target !== emptyTarget && (await readFile(target, "utf8")) === content,
  );
  await page
    .getByText(
      "Export has no eligible records. Check matching alternatives, split, and provenance.",
      { exact: true },
    )
    .waitFor();
  downloads.push({
    format: "atif",
    quality: "passed",
    rows: 0,
    filename: passedFilename,
    suggested_filename: empty.suggestedFilename(),
  });
  await page.getByLabel("Export quality").selectOption("all");
  await page.getByRole("tab", { name: "Provenance", exact: true }).click();
  await page.locator(".frozen-provenance summary").first().click();
  await screenshot("desktop-atif-provenance.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await withinViewport("Mobile ATIF inspector");
  await screenshot("mobile-atif-inspector.png");
  await page.getByLabel("Export format").scrollIntoViewIfNeeded();
  await screenshot("mobile-atif-controls.png");
  check("ATIF phase has no browser errors", errors.length === 0);
  const scope = ["web/src/api.ts", "web/src/App.tsx", "scripts/ui-qa.mjs"];
  const files = {};
  for (const file of scope)
    files[file] = createHash("sha256")
      .update(await readFile(path.join(root, file)))
      .digest("hex");
  const revision = execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {
    encoding: "utf8",
    timeout: 2000,
  }).trim();
  const dirty = execFileSync(
    "git",
    [
      "-C",
      root,
      "status",
      "--porcelain",
      "--untracked-files=all",
      "--",
      ...scope,
    ],
    { encoding: "utf8", timeout: 2000 },
  ).trim();
  completedReport = { downloads, video: await page.video().path() };
  await writeFile(
    path.join(output, "ui-report.json"),
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        phase: "atif",
        base_url: baseURL,
        run_id: created.id,
        checks,
        downloads,
        text_contrast: contrastResults,
        browser_errors: errors,
        controller_source: {
          revision,
          files,
          source_dirty: Boolean(dirty),
          source_dirty_scope: scope,
        },
        api_episode_provenance: detail.episodes[0].provenance,
        provider_calls: 0,
        paid_calls: 0,
        video: completedReport.video,
      },
      null,
      2,
    ),
  );
  console.log(
    `ATIF UI QA passed: ${checks.length} checks, ${trajectories.length} recorded evaluation episodes; ${output}`,
  );
}

async function runAccessQA() {
  const healthResponse = await context.request.get("/api/health");
  check("Access API responds through the local Vite proxy", healthResponse.ok());
  const health = await healthResponse.json();
  const catalogResponse = await context.request.get("/api/environments");
  const { environments } = await catalogResponse.json();
  const world = environments.find((environment) => environment.id === "access-provisioning");
  check("Actual catalog contains the synthetic partial-observation access world",
    Boolean(world) && world.tags.includes("partial-observation") &&
    world.tools.some((tool) => tool.name === "search_employees") &&
    world.tools.some((tool) => tool.name === "grant_access"));
  const revision = execFileSync("git", ["-C", root, "rev-parse", "HEAD"],
    { encoding: "utf8", timeout: 2000 }).trim();
  const scope = ["src/world_engine", "web/src", "web/package.json", "web/package-lock.json",
    "scripts/ui-qa.mjs", "tests/test_ui_qa.py", "pyproject.toml", "uv.lock"];
  const dirty = execFileSync("git", ["-C", root, "status", "--porcelain", "--untracked-files=all", "--", ...scope],
    { encoding: "utf8", timeout: 2000 }).trim();
  check("Access QA uses a committed controller and runtime source scope", !dirty);
  const files = {};
  const tracked = execFileSync("git", ["-C", root, "ls-files", "--", ...scope],
    { encoding: "utf8", timeout: 2000 }).trim().split("\n");
  for (const file of tracked)
    files[file] = createHash("sha256").update(await readFile(path.join(root, file))).digest("hex");
  const details = [];
  const rawDetails = [];
  const operatorEpisodes = [];
  for (const provider of ["scripted-oracle", "scripted-baseline"]) {
    await page.goto("/#runs");
    await page.getByText("Runtime connected", { exact: true }).waitFor();
    await page.getByRole("button", { name: "New rollout", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "New rollout" });
    await dialog.getByLabel("Run label").fill(`QA / Access ${provider}`);
    await dialog.getByLabel("Environment", { exact: true }).selectOption("access-provisioning");
    await dialog.getByLabel("Provider", { exact: true }).selectOption(provider);
    await dialog.getByLabel("Episodes", { exact: true }).fill("8");
    await dialog.getByLabel("Starting seed").fill("0");
    await dialog.getByLabel("Max steps / episode").fill("20");
    await dialog.getByLabel("Timeout / episode (s)").fill("30");
    await dialog.getByLabel("Concurrency", { exact: true }).fill("1");
    await dialog.getByRole("checkbox", {
      name: "Evaluation-only batch (excluded from training exports)",
    }).check();
    if (provider === "scripted-oracle") await screenshot("desktop-access-new-rollout.png");
    const createdPromise = page.waitForResponse((response) =>
      response.url().endsWith("/api/runs") && response.request().method() === "POST");
    await dialog.getByRole("button", { name: "Start rollout", exact: true }).click();
    const createdResponse = await createdPromise;
    check(`${provider}: actual API accepts the UI configuration`, createdResponse.ok());
    const created = await createdResponse.json();
    assert.equal(created.config.environment_id, "access-provisioning");
    assert.equal(created.config.provider_id, provider);
    assert.equal(created.config.episodes, 8);
    assert.equal(created.config.seed, 0);
    assert.equal(created.config.max_steps, 20);
    assert.equal(created.config.timeout_seconds, 30);
    assert.equal(created.config.concurrency, 1);
    assert.equal(created.config.evaluation_only, true);
    assert.equal(created.config.allow_paid, false);
    await page.waitForURL(`**/#runs/${created.id}`);
    await page.locator(".detail-subtitle .status-completed").waitFor();
    await page.getByText("Hidden grader", { exact: true }).waitFor();
    const detailResponse = await context.request.get(`/api/runs/${created.id}`);
    assert.ok(detailResponse.ok());
    const rawDetail = await detailResponse.text();
    rawDetails.push(rawDetail);
    const detail = JSON.parse(rawDetail);
    assert.equal(detail.episodes.length, 8);
    assert.deepEqual(detail.episodes.map((episode) => episode.seed).sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6, 7]);
    for (const episode of detail.episodes) {
      assert.equal(episode.provenance.environment_id, world.id);
      assert.equal(episode.provenance.environment_version, world.version);
      assert.equal(episode.provenance.git_revision, revision);
      assert.equal(episode.provenance.implementation_dirty, false);
      assert.equal(episode.provenance.evaluation_only, true);
      assert.equal(episode.provenance.provider_id, provider);
      assert.equal(episode.termination, "finished");
      assert.ok(episode.steps > 0 && episode.steps <= 20);
      assert.equal(episode.passed, provider === "scripted-oracle");
      let observation = episode.initial_observation;
      const history = [];
      for (const step of episode.trace) {
        assert.deepEqual(Object.keys(observation.state).sort(), ["assigned_request_id", "current_view"]);
        assert.deepEqual(observation.tools.map((tool) => tool.name), world.tools.map((tool) => tool.name));
        assert.equal(step.policy_input.length, 2);
        assert.equal(step.policy_input[0].role, "system");
        assert.equal(step.policy_input[1].role, "user");
        assert.deepEqual(JSON.parse(step.policy_input[1].content), { observation, history });
        history.push({ action: step.action, result: step.result });
        observation = step.observation;
      }
      assert.deepEqual(Object.keys(episode.final_observation.state).sort(), ["assigned_request_id", "current_view"]);
      assert.ok(Buffer.byteLength(JSON.stringify(episode)) <= 1024 * 1024);
      operatorEpisodes.push(episode);
    }
    check(`${provider}: eight recorded episodes preserve committed provenance and bounded partial contexts`, true);
    await withinViewport(`Desktop access ${provider}`);
    await checkTextContrast(`Access ${provider} inspector`);
    await screenshot(`desktop-access-${provider}.png`);
    for (const format of ["traces", "atif", "sft", "dpo", "grpo"]) {
      await page.getByLabel("Export format").selectOption(format);
      await page.getByLabel("Export quality").selectOption("all");
      const downloadPromise = page.waitForEvent("download");
      const responsePromise = page.waitForResponse((response) =>
        response.url().includes(`format=${format}`) && response.url().includes("quality=all"));
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const download = await downloadPromise;
      const response = await responsePromise;
      const filename = `${created.id}-${format}-all.jsonl`;
      await download.saveAs(path.join(output, filename));
      const content = await readFile(path.join(output, filename), "utf8");
      const rows = content.trim() ? content.trim().split("\n").map((line) => JSON.parse(line)) : [];
      const expected = ["traces", "atif"].includes(format) ? 8 : 0;
      check(`${provider}: ${format} preserves evaluation-only export boundary`,
        response.ok() && rows.length === expected && response.headers()["x-export-records"] === String(expected));
      if (format === "traces") {
        assert.deepEqual(rows.map((record) => record.passed), detail.episodes.map((episode) => episode.passed));
        assert.ok(rows.every((record) => record.provenance.evaluation_only === true));
      }
      if (format === "atif") {
        assert.ok(rows.every((record) => record.schema_version === "ATIF-v1.8" &&
          record.extra.evaluation_only === true && record.extra.training_eligible === false));
        assert.deepEqual(rows.map((record) => record.extra.world_engine.passed), detail.episodes.map((episode) => episode.passed));
      }
      downloads.push({ format, quality: "all", run_id: created.id, rows: rows.length, filename,
        suggested_filename: download.suggestedFilename(), sha256: createHash("sha256").update(content).digest("hex") });
    }
    await page.getByRole("tab", { name: "Provenance", exact: true }).click();
    await page.locator(".frozen-provenance summary").first().click();
    await screenshot(`desktop-access-${provider}-provenance.png`);
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      await withinViewport(`Mobile ${width} access ${provider} provenance`);
      await screenshot(`mobile-${width}-access-${provider}-provenance.png`);
      await page.getByRole("tab", { name: "Episode traces", exact: true }).click();
      await page.locator(".trace-layout").scrollIntoViewIfNeeded();
      await withinViewport(`Mobile ${width} access ${provider} timeline`);
      await screenshot(`mobile-${width}-access-${provider}-trace.png`);
      await page.getByRole("tab", { name: "Provenance", exact: true }).click();
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    details.push(detail);
  }
  const encoded = operatorEpisodeJsonl(rawDetails);
  assert.ok(Buffer.byteLength(encoded) <= 16 * 1024 * 1024);
  const operatorFilename = "access-evaluation-episodes.jsonl";
  await writeFile(path.join(output, operatorFilename), encoded, { flag: "wx" });
  const replayOutput = execFileSync("uv", ["run", "python", "-m", "world_engine", "replay", "--file", path.join(output, operatorFilename)],
    { cwd: root, encoding: "utf8", timeout: 30000, maxBuffer: 1024 * 1024 });
  const verified = JSON.parse(replayOutput);
  check("All sixteen full operator episodes pass current-source CLI replay", verified.verified_episodes === 16 &&
    verified.results.every((result) => result.verified === true));
  await writeFile(path.join(output, "access-replay.json"), JSON.stringify(verified, null, 2), { flag: "wx" });
  check("Access phase has no browser runtime errors", errors.length === 0);
  completedReport = { downloads, video: await page.video().path() };
  await writeFile(path.join(output, "ui-report.json"), JSON.stringify({
    generated_at: new Date().toISOString(), phase: "access", base_url: baseURL,
    controller_source: { revision, files, source_dirty: false, source_dirty_scope: scope },
    api_health: health, api_episode_provenance: details.map((detail) => detail.episodes[0].provenance),
    run_ids: details.map((detail) => detail.id), protocol: { environment_id: world.id,
      providers: ["scripted-oracle", "scripted-baseline"], seeds: [0, 1, 2, 3, 4, 5, 6, 7],
      episodes: 16, max_steps: 20, timeout_seconds: 30, concurrency: 1, evaluation_only: true },
    model_calls: 0, paid_calls: 0, local_cancellation_requested: false,
    outcome_control_only: true, training_eligible: false, checks, downloads,
    real_episode_count: 16, real_trace_steps: operatorEpisodes.reduce((total, episode) => total + episode.steps, 0),
    operator_episode_file: operatorFilename, operator_episode_sha256: createHash("sha256").update(encoded).digest("hex"),
    replay_file: "access-replay.json", text_contrast: contrastResults, browser_errors: errors, video: completedReport.video,
  }, null, 2), { flag: "wx" });
  console.log(`Access UI QA passed: ${checks.length} checks, 16 scripted evaluation episodes; ${output}`);
}

try {
  if (options.phase === "atif") {
    await runAtifQA();
  } else if (options.phase === "access") {
    await runAccessQA();
  } else {
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
    await page
      .getByRole("button", { name: "New rollout", exact: true })
      .click();
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
    await page
      .getByRole("button", { name: "New rollout", exact: true })
      .click();
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
      await page.getByRole("heading", { name: "No matching runs on this page", exact: true }).isVisible(),
    );
    await page.getByLabel("Search runs").fill("");
    await page
      .getByRole("link", { name: "World library", exact: true })
      .click();
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
    if (options.localCancel && local) {
      await page
        .getByRole("link", { name: "Rollout runs", exact: true })
        .click();
      await page
        .getByRole("button", { name: "New rollout", exact: true })
        .click();
      const cancellationDialog = page.getByRole("dialog", {
        name: "New rollout",
      });
      await cancellationDialog
        .getByLabel("Run label")
        .fill("QA / cancellation");
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
      await page
        .getByRole("button", { name: "Cancel run", exact: true })
        .click();
      await page.locator(".detail-subtitle .status-cancelled").waitFor();
      const final = await context.request.get(
        `/api/runs/${cancellationRun.id}`,
      );
      check(
        "Live local job cancels through the UI",
        (await final.json()).status === "cancelled",
      );
    } else
      checks.push(options.localCancel ? "Local cancellation not exercised: provider unavailable"
        : "Local cancellation not requested: no local inference");

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
    await page
      .getByRole("button", { name: "New rollout", exact: true })
      .click();
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
  }
} finally {
  await context.close();
  await browser.close();
}

}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  await main(parseOptions(process.argv.slice(2)));
