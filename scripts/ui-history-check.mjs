import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
const { chromium } = require("playwright");
const viteRoot = path.dirname(require.resolve("vite/package.json"));
const { createServer } = await import(pathToFileURL(path.join(viteRoot, "dist/node/index.js")).href);
const server = await createServer({ root: path.join(root, "web"), logLevel: "error",
  server: { host: "127.0.0.1", port: 0, strictPort: false, watch: null } });
let browser;

try {
  await server.listen();
  const url = server.resolvedUrls.local[0];
  assert.ok(url, "mock test requires a loopback Vite URL");
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const config = { environment_id: "crm-merge", provider_id: "scripted-oracle", episodes: 1,
    seed: 42, max_steps: 20, concurrency: 1, model: null, allow_paid: false,
    timeout_seconds: 30, label: "", evaluation_only: true };
  const runs = Array.from({ length: 75 }, (_, index) => ({
    id: `run-${index}`, label: `Run ${index}`, status: "completed",
    created_at: "2026-10-10T12:00:00Z", updated_at: "2026-10-10T12:00:00Z", config,
    total_episodes: 1, completed_episodes: 1, passed_episodes: 1, failed_episodes: 0,
    mean_reward: 1, success_rate: 1, elapsed_seconds: 1, steps_per_second: 5, error: null,
  }));
  const requests = [];
  const errors = [];
  let failOlder = false;
  let emptyOlder = false;
  let delayNewest = false;
  let slowNewest = false;
  let created;
  let expectedProvider = "scripted-oracle";
  let expectedModel = null;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const target = new URL(request.url());
    let response;
    if (target.pathname === "/api/health") {
      response = { status: "ok", version: "test", execution: "mocked", active_runs: 7 };
    } else if (target.pathname === "/api/environments") {
      response = { environments: [{ id: "crm-merge", name: "CRM", description: "Synthetic fixture",
        version: "1", tools: [], tags: [] }] };
    } else if (target.pathname === "/api/providers") {
      response = { providers: [{ id: "scripted-oracle", name: "Reference", kind: "scripted",
        configured: true, requires_opt_in: false, models: [] },
        ...["local", "local-tools", "local-tools-ledger"].map((id) => ({
          id, name: id, kind: "local", configured: true, requires_opt_in: false,
          models: ["operator-model:custom", "qwen3:8b"],
        }))] };
    } else if (target.pathname === "/api/runs" && request.method() === "GET") {
      const limit = Number(target.searchParams.get("limit"));
      const offset = Number(target.searchParams.get("offset"));
      assert.equal(limit, 51, "only one bounded page plus a lookahead is requested");
      assert.ok(Number.isInteger(offset) && offset >= 0 && offset <= 100000);
      requests.push(offset);
      if (offset === 50 && failOlder) {
        failOlder = false;
        await route.fulfill({ status: 503, json: { detail: "Mock history failure" } });
        return;
      }
      if (offset === 0 && delayNewest) {
        delayNewest = false;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      if (offset === 0 && slowNewest) {
        slowNewest = false;
        await new Promise((resolve) => setTimeout(resolve, 2800));
      }
      response = { runs: offset === 50 && emptyOlder ? [] : runs.slice(offset, offset + limit) };
    } else if (target.pathname === "/api/runs" && request.method() === "POST") {
      const submitted = request.postDataJSON();
      assert.equal(submitted.provider_id, expectedProvider);
      assert.equal(submitted.allow_paid, false);
      assert.equal(submitted.model, expectedModel);
      if (expectedProvider === "local-tools" || expectedProvider === "local-tools-ledger")
        assert.equal(submitted.evaluation_only, true);
      created = { ...runs[0], id: "created-run", label: "Created mock run", status: "queued", config: submitted };
      runs.unshift(created);
      response = created;
    } else if (target.pathname.startsWith("/api/runs/")) {
      const id = decodeURIComponent(target.pathname.slice("/api/runs/".length));
      const run = runs.find((item) => item.id === id);
      assert.ok(run, "detail request must refer to a known mock run");
      response = { ...run, episodes: [] };
    } else {
      assert.fail(`Unexpected API request: ${request.method()} ${target.pathname}`);
    }
    await route.fulfill({ json: response });
  });
  const pager = () => page.getByRole("navigation", { name: "Run history pages", exact: true }).first();
  const waitPage = async (number, count) => {
    await pager().getByRole("status").filter({ hasText: `Page ${number} / Runs` }).waitFor();
    assert.equal(await page.locator(".run-table tbody tr").count(), count);
  };
  await page.goto(url);
  await waitPage(1, 50);
  assert.equal(await pager().getByRole("button", { name: "Newer runs", exact: true }).isDisabled(), true);
  assert.equal(await page.locator(".metric").filter({ hasText: "Runs on page" }).locator("strong").textContent(), "50");
  assert.equal(await page.locator(".nav-count").textContent(), "7", "global activity comes from health, not the loaded page");
  assert.equal(await page.getByText("Total runs", { exact: true }).count(), 0);
  await page.goto(`${url}#runs/run-69`);
  await page.getByRole("heading", { name: "Run 69", exact: true }).waitFor();
  await page.getByRole("link", { name: "Run history", exact: true }).click();
  await waitPage(1, 50);
  slowNewest = true;
  runs[0].completed_episodes = 2;
  const beforeSlow = requests.filter((offset) => offset === 0).length;
  await page.getByRole("button", { name: "Refresh runtime data", exact: true }).click();
  await page.waitForTimeout(2300);
  assert.equal(requests.filter((offset) => offset === 0).length, beforeSlow + 1,
    "same-page polls must not overlap a slow in-flight request");
  await page.waitForFunction(() => [...document.querySelectorAll(".metric")].some((metric) =>
    metric.textContent.includes("Page episodes") && metric.querySelector("strong")?.textContent === "51"));

  await page.getByRole("link", { name: "Benchmarks", exact: true }).click();
  await page.getByRole("checkbox", { name: "Compare Run 0", exact: true }).check();
  await page.getByRole("link", { name: /^Rollout runs/ }).click();
  failOlder = true;
  await pager().getByRole("button", { name: "Older runs", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Mock history failure" }).waitFor();
  assert.equal(await page.locator(".run-table tbody tr").count(), 0, "failed page must not display a previous page's rows");
  await page.getByRole("button", { name: "Retry history", exact: true }).click();
  await waitPage(2, 25);
  assert.equal(await pager().getByRole("button", { name: "Older runs", exact: true }).isDisabled(), true);
  assert.equal(await page.locator(".metric").filter({ has: page.getByText("Page episodes", { exact: true }) }).locator("strong").textContent(), "25");
  await page.getByRole("link", { name: "Benchmarks", exact: true }).click();
  assert.equal(await page.getByRole("checkbox", { name: "Compare Run 0", exact: true }).isChecked(), true);
  await page.getByRole("link", { name: /^Rollout runs/ }).click();
  await page.getByRole("textbox", { name: "Search runs on this page" }).fill("Run 74");
  await page.getByRole("link", { name: "Run 74", exact: true }).waitFor();
  assert.equal(await page.locator(".run-table tbody tr").count(), 1);
  assert.equal(await page.locator(".metric").filter({ hasText: "Runs on page" }).locator("strong").textContent(), "25");
  await page.getByRole("textbox", { name: "Search runs on this page" }).fill("");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  const controls = await pager().boundingBox();
  assert.ok(controls && controls.x >= 0 && controls.x + controls.width <= 391);
  await page.setViewportSize({ width: 1440, height: 960 });

  runs[50].completed_episodes = 2;
  await page.waitForFunction(() => [...document.querySelectorAll(".metric")].some((metric) =>
    metric.textContent.includes("Page episodes") && metric.querySelector("strong")?.textContent === "26"));
  await page.getByRole("link", { name: "Run 69", exact: true }).click();
  await page.getByRole("heading", { name: "Run 69", exact: true }).waitFor();
  await page.getByRole("link", { name: "Run history", exact: true }).click();
  await waitPage(2, 25);

  await pager().getByRole("button", { name: "Newest runs", exact: true }).click();
  await waitPage(1, 50);
  emptyOlder = true;
  await pager().getByRole("button", { name: "Older runs", exact: true }).click();
  await page.getByRole("heading", { name: "No runs on this page", exact: true }).waitFor();
  assert.equal(await pager().getByRole("button", { name: "Newer runs", exact: true }).isEnabled(), true);
  emptyOlder = false;
  await pager().getByRole("button", { name: "Newer runs", exact: true }).click();
  await waitPage(1, 50);
  delayNewest = true;
  await page.getByRole("button", { name: "Refresh runtime data", exact: true }).click();
  await pager().getByRole("button", { name: "Older runs", exact: true }).click();
  await waitPage(2, 25);
  await page.waitForTimeout(600);
  await waitPage(2, 25);

  await page.getByRole("button", { name: "New rollout", exact: true }).click();
  await page.getByRole("button", { name: "Start rollout", exact: true }).click();
  await page.getByRole("heading", { name: "Created mock run", exact: true }).waitFor();
  await page.getByRole("link", { name: "Run history", exact: true }).click();
  await waitPage(1, 50);
  assert.ok(created && requests.includes(50));
  await page.getByRole("link", { name: "Created mock run", exact: true }).waitFor();
  for (const native of ["local-tools", "local-tools-ledger"]) {
    await page.getByRole("button", { name: "New rollout", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "New rollout", exact: true });
    const evaluation = dialog.getByRole("checkbox", { name: "Evaluation-only batch (excluded from training exports)", exact: true });
    assert.equal(await evaluation.isChecked(), false);
    assert.equal(await evaluation.isEnabled(), true);
    await dialog.getByLabel("Provider", { exact: true }).selectOption(native);
    assert.equal(await evaluation.isChecked(), true);
    assert.equal(await evaluation.isDisabled(), true);
    assert.equal(await dialog.getByLabel("Model", { exact: true }).inputValue(), "qwen3:8b");
    assert.equal(await dialog.locator(".paid-consent").count(), 0);
    await dialog.getByLabel("Provider", { exact: true }).selectOption("local");
    assert.equal(await evaluation.isEnabled(), true);
    await evaluation.uncheck();
    await dialog.getByLabel("Provider", { exact: true }).selectOption(native);
    assert.equal(await evaluation.isChecked(), true);
    assert.equal(await evaluation.isDisabled(), true);
    expectedProvider = native;
    expectedModel = native === "local-tools" ? "qwen3:8b" : "operator-model:custom";
    await dialog.getByLabel("Model", { exact: true }).selectOption(expectedModel);
    await dialog.getByRole("button", { name: "Start rollout", exact: true }).click();
    await page.getByRole("heading", { name: "Created mock run", exact: true }).waitFor();
    assert.equal(created.config.provider_id, native);
    assert.equal(created.config.evaluation_only, true);
    assert.equal(created.config.model, expectedModel);
    assert.equal(created.config.allow_paid, false);
    await page.getByRole("link", { name: "Run history", exact: true }).click();
    await waitPage(1, 50);
  }
  assert.deepEqual(errors, []);
  console.log("Run history and native provider selection: bounded pagination, honest metrics, failure/retry, polling, creation, mobile layout and evaluation-only native requests passed against mocked API only.");
} finally {
  await browser?.close();
  await server.close();
}
