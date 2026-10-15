import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: { url: { type: "string" }, output: { type: "string" } } });
assert.ok(values.url && values.output, "Explicit test server URL and fresh output are required");
const origin = new URL(values.url);
assert.equal(origin.hostname, "127.0.0.1", "QA only targets a separate loopback test server");
assert.equal(origin.pathname, "/");
assert.ok(!origin.search && !origin.hash && !origin.username && !origin.password);
const output = path.resolve(values.output);
try {
  await lstat(output);
  throw new Error("QA output exists; refusing to overwrite evidence");
} catch (error) { if (error.code !== "ENOENT") throw error; }
await mkdir(path.dirname(output), { recursive: true });
await mkdir(output);

const initial = await fetch(new URL("/api/progress", origin)).then((r) => r.json());
assert.deepEqual(initial.answers, {}, "Use a fresh QA database, never the learner's answers");
assert.equal(initial.updatedAt, null, "Previously used state is not a fresh QA database");
const lesson = await fetch(new URL("/api/lesson", origin)).then((r) => r.json());
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
const { chromium } = require("playwright");
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 },
  recordVideo: { dir: path.join(output, "video"), size: { width: 1440, height: 1000 } } });
const errors = [], blocked = [], checks = [], screenshots = [];
await context.addInitScript(({ id, version }) => {
  const stale = JSON.stringify({ step: 5, answers: { "q-task": "STALE LESSON RESPONSE" }, checked: {} });
  const prefix = "world-engine.learning." + id + ".v" + version;
  localStorage.setItem(prefix, stale);
  localStorage.setItem(prefix + "." + "0".repeat(64), stale);
}, { id: lesson.id, version: lesson.version });
const page = await context.newPage();
page.on("pageerror", (e) => errors.push(e.message));
await context.route("**/*", async (route) => {
  const request = route.request(), url = new URL(request.url());
  if (url.origin !== origin.origin || !["GET", "PUT"].includes(request.method()) ||
      (request.method() === "PUT" && url.pathname !== "/api/progress")) {
    blocked.push({ method: request.method(), path: url.pathname });
    return route.abort();
  }
  return route.continue();
});
const check = (name, value) => { assert.ok(value, name); checks.push(name); };
const snapshot = async (name) => {
  check(`${name}: no horizontal overflow`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  screenshots.push(name);
};
const navigate = async (step) => {
  await page.locator("#steps button").nth(step).click();
  await page.waitForFunction((n) => document.querySelectorAll("#steps button")[n]?.getAttribute("aria-current") === "step", step);
};
const saved = () => page.waitForFunction(() => document.getElementById("save-status").textContent === "Saved on this computer");
let report;
try {
  await page.goto(origin.href);
  await page.locator("#answer-q-task").waitFor();
  check("Drafts from another lesson revision are not restored", await page.locator("#answer-q-task").inputValue() === "");
  await snapshot("desktop-01-task.png");
  check("Only sanitized lesson data is served", !Object.hasOwn(lesson, "media"));
  await page.getByText("Original task and run", { exact: true }).click();
  check("Exact recorded task is available", await page.getByText(lesson.task, { exact: true }).isVisible());
  await page.getByText("Original task and run", { exact: true }).click();

  let draft = "QA ONLY: Update the existing incident, not a new project. Preserve other records. <script>not executable</script>";
  await page.locator("#answer-q-task").fill(draft);
  await navigate(1);
  await saved();
  await page.reload();
  check("Current step persists after reload", await page.locator("#steps button").nth(1).getAttribute("aria-current") === "step");
  await navigate(0);
  check("Written answer persists after reload", await page.locator("#answer-q-task").inputValue() === draft);
  let failNextSave = true;
  await page.route("**/api/progress", async (route) => {
    if (route.request().method() === "PUT" && failNextSave) {
      failNextSave = false;
      return route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"QA simulated save failure"}' });
    }
    return route.fallback();
  });
  draft += " A failed save must retain this draft.";
  await page.locator("#answer-q-task").fill(draft);
  await page.locator("#retry-save").waitFor({ state: "visible" });
  check("Save failure is visible, not reported as saved", (await page.locator("#save-status").textContent()).includes("Not saved to disk"));
  await page.locator("#retry-save").click();
  await saved();
  await page.reload();
  check("Retry persists the previously failed draft", await page.locator("#answer-q-task").inputValue() === draft);

  for (let step = 1; step <= 4; step += 1) {
    await navigate(step);
    const question = lesson.questions.find((q) => q.id === lesson.sections[step].questionId);
    const wrong = question.choices.find((c) => c.id !== question.correctChoice);
    await page.locator(`input[name="${question.id}"][value="${wrong.id}"]`).check();
    await page.getByRole("button", { name: "Check my reasoning" }).click();
    check(`${question.id}: wrong choice explains reasoning`, await page.locator(".feedback").textContent() === question.explanations[wrong.id]);
    await page.locator(`input[name="${question.id}"][value="${question.correctChoice}"]`).check();
    check(`${question.id}: changing choice hides stale feedback`, await page.locator(".feedback").isHidden());
    await page.getByRole("button", { name: "Check my reasoning" }).click();
    check(`${question.id}: right choice explains reasoning`, await page.locator(".feedback").textContent() === question.explanations[question.correctChoice]);
    await saved();
    if (step === 3) {
      await page.locator("video").evaluate(async (video) => {
        if (video.readyState < 1) await new Promise((resolve, reject) => { video.addEventListener("loadedmetadata", resolve, { once: true }); video.addEventListener("error", reject, { once: true }); });
        video.currentTime = 135;
        if (video.seeking) await new Promise((resolve) => video.addEventListener("seeked", resolve, { once: true }));
        await video.play();
      });
      await page.waitForFunction(() => document.querySelector("video").currentTime > 135.1);
      const playback = await page.locator("video").evaluate((v) => { v.pause(); return { seconds: v.currentTime, duration: v.duration, width: v.videoWidth, frames: v.getVideoPlaybackQuality().totalVideoFrames }; });
      check("Actual rollout video decodes, seeks and plays", playback.frames > 0 && playback.width > 0 && playback.duration > 600);
      await snapshot("desktop-04-action-video.png");
    } else await snapshot(`desktop-0${step + 1}-${lesson.sections[step].id}.png`);
  }

  await navigate(5);
  const explanation = "QA ONLY: The model saw accessibility text and created an extra project. The target stayed unchanged, so the grade was zero. Cancel is a proposed next step, not a recorded recovery.";
  await page.locator("#answer-q-explain").fill(explanation);
  await page.getByRole("button", { name: "Ready for review" }).click();
  await page.getByText("Saved for discussion. Tell Codex: Lesson 1 is ready for review.", { exact: true }).waitFor();
  check("Written answers are displayed literally", (await page.locator(".review-answer").first().textContent()) === draft);
  check("No injected script element", await page.locator(".review script").count() === 0);
  await snapshot("desktop-06-review.png");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export").click();
  const download = await downloadPromise;
  await download.saveAs(path.join(output, "qa-progress-export.json"));
  const exported = JSON.parse(await readFile(path.join(output, "qa-progress-export.json"), "utf8"));
  check("Export contains actual persisted answers", exported.answers["q-task"] === draft && exported.answers["q-explain"] === explanation);
  await page.reload();
  check("Final written answer persists after reload", await page.locator("#answer-q-explain").inputValue() === explanation);
  for (const width of [390, 360]) {
    await page.setViewportSize({ width, height: 844 });
    for (let step = 0; step < 6; step += 1) {
      await navigate(step);
      await snapshot(`mobile-${width}-${lesson.sections[step].id}.png`);
    }
  }
  check("No browser errors", errors.length === 0);
  check("No external or rollout-mutating requests", blocked.length === 0);
  report = { ok: true, lessonId: lesson.id, attemptId: lesson.attemptId, checks, screenshots, errors, blocked,
    note: "QA writes only to its fresh test database. Desktop video playback checked; mobile checks are layout-only." };
} catch (error) {
  report = { ok: false, checks, screenshots, errors, blocked, error: error.message };
  throw error;
} finally {
  await context.close();
  await browser.close();
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ ok: report.ok, checks: checks.length, screenshots: screenshots.length, output }));
