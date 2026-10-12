import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
const viteRoot = path.dirname(require.resolve("vite/package.json"));
const { createServer } = await import(
  pathToFileURL(path.join(viteRoot, "dist/node/index.js")).href
);
const { default: react } = await import(
  pathToFileURL(require.resolve("@vitejs/plugin-react")).href
);
const server = await createServer({
  root: path.join(root, "web"),
  configFile: false,
  plugins: [react()],
  logLevel: "error",
  server: { host: "127.0.0.1", port: 5187, strictPort: false, watch: null },
});
let browser;
try {
  const boundary = await server.ssrLoadModule("/src/browserApi.ts");
  const id = "11111111-1111-4111-8111-111111111111";
  const hash = "a".repeat(64);
  const task = {
    id: "gitlab-release",
    version: "1",
    name: "GitLab release handoff",
    instruction: "Inspect the issue and complete the release handoff.",
    application: "GitLab",
    application_version: "17.8.0",
    image_digest: `sha256:${hash}`,
    fixture_hash: hash,
    grader_version: "gitlab-verifier-v1",
    observation_mode: "AX",
    evaluation_only: true,
  };
  const config = {
    task_id: task.id,
    provider_id: "local-browser",
    model: "qwen3:8b",
    seed: 42,
    max_steps: 30,
    timeout_seconds: 180,
  };
  const grade = {
    passed: true,
    reward: 1,
    checks: [
      {
        name: "Issue closed",
        passed: true,
        detail: "Sealed application state confirms the requested change.",
      },
    ],
    grader_version: task.grader_version,
    sealed_state_sha256: hash,
  };
  const summary = {
    schema: "world-engine.browser.v1",
    id,
    config,
    task,
    provenance: { evaluation_only: true, training_eligible: false },
    created_at: "2026-10-10T12:00:00Z",
    updated_at: "2026-10-10T12:00:05Z",
    status: "completed",
    termination: "finished",
    steps: 1,
    invalid_actions: 0,
    passed: true,
    reward: 1,
    outcome: grade,
    error: null,
    elapsed_seconds: 5,
    phase_seconds: { rollout: 2, grade: 1 },
    cleanup: { status: "completed", error_code: null },
  };
  const observation = (frame, text) => ({
    url: "http://gitlab.internal/release/issues/1",
    title: "Release handoff",
    accessibility_text: text,
    screenshot_artifact_id: `frames/${frame}.png`,
    observation_mode: "AX",
    image_not_sent_to_model: true,
  });
  const initial = observation(
    "000",
    "[1] button 'Close issue'\nFull recorded AX tail",
  );
  const modelInput = {
    task: task.instruction,
    observation: {
      url: initial.url,
      title: initial.title,
      accessibility_text: "[1] button 'Close issue'",
      observation_mode: "AX",
      image_not_sent_to_model: true,
      accessibility_truncated: true,
    },
    history: [],
  };
  const journal = [
    ["created", { summary }],
    ["observation", { step: 0, observation: initial }],
    [
      "inference_intent",
      {
        request_body: {
          messages: [{ role: "user", content: JSON.stringify(modelInput) }],
        },
        request_bytes: 400,
        request_sha256: hash,
      },
    ],
    [
      "action_intent",
      { step: 0, action: { kind: "click", bid: "1" }, evidence: {} },
    ],
    [
      "action_result",
      {
        step: 0,
        action: { kind: "click", bid: "1" },
        result: { ok: true },
        elapsed_ms: 20,
      },
    ],
    [
      "observation",
      { step: 1, observation: observation("001", "[2] text 'Closed'") },
    ],
    ["browser_closed", {}],
    ["state_sealed", { sha256: hash, size_bytes: 50 }],
    ["graded", { outcome: grade }],
    ["cleanup", summary.cleanup],
  ].map(([event, data], sequence) => ({
    schema: "world-engine.browser.v1",
    attempt_id: id,
    sequence,
    event,
    data,
    at: "2026-10-10T12:00:00Z",
    previous_hash: hash,
    content_hash: hash,
  }));
  const artifacts = ["000", "001"].map((frame) => ({
    id: `frames/${frame}.png`,
    kind: "screenshot",
    mime_type: "image/png",
    size_bytes: 68,
    sha256: hash,
    url: `/api/browser/attempts/${id}/artifacts/frames/${frame}.png`,
  }));
  const detail = { ...summary, journal, artifacts };
  assert.equal(boundary.browserDetailSchema.safeParse(detail).success, true);
  assert.deepEqual(boundary.recordedModelInput(detail, 1), {
    kind: "v2",
    context: modelInput,
    observation: modelInput.observation,
  });
  const v3Context = {
    observation: {
      ...modelInput.observation,
      accessibility_sha256: hash,
      accessibility_chars: initial.accessibility_text.length,
      accessibility_omitted: false,
    },
    next_step: 1,
    remaining_actions: 29,
    feedback: {
      consecutive_same_action: 1,
      consecutive_unchanged_observations: 0,
      first_action_transition_known: false,
      ok_means: "execution_only_not_task_progress",
    },
  };
  const v3RequestBody = {
    model: "qwen3:32b",
    messages: [
      { role: "system", content: "Generic browser policy context" },
      { role: "user", content: JSON.stringify({ task: task.instruction }) },
      {
        role: "assistant",
        content: "",
        tool_calls: [
          { function: { name: "browser_click", arguments: { bid: "1" } } },
        ],
      },
      {
        role: "tool",
        tool_name: "browser_click",
        content: JSON.stringify({
          completed_step: 0,
          result: { ok: true },
          observation: {
            url: initial.url,
            title: initial.title,
            accessibility_sha256: hash,
            accessibility_chars: initial.accessibility_text.length,
            accessibility_omitted: true,
            observation_mode: "AX",
            image_not_sent_to_model: true,
          },
        }),
      },
      { role: "user", content: JSON.stringify(v3Context) },
    ],
    tools: [{ type: "function", function: { name: "browser_click" } }],
    options: { temperature: 0, num_predict: 512, num_ctx: 16384 },
    stream: false,
    think: false,
    keep_alive: "5m",
  };
  const withRequest = (requestBody) => ({
    ...detail,
    journal: journal.map((entry) =>
      entry.event === "inference_intent"
        ? { ...entry, data: { ...entry.data, request_body: requestBody } }
        : entry,
    ),
  });
  const v3Detail = {
    ...withRequest(v3RequestBody),
    config: { ...config, model: "qwen3:32b" },
  };
  const requestBefore = JSON.stringify(v3RequestBody);
  const parsedV3 = boundary.recordedModelInput(v3Detail, 1);
  assert.deepEqual(parsedV3, {
    kind: "v3",
    requestBody: v3RequestBody,
    observation: v3Context.observation,
  });
  assert.equal(JSON.stringify(parsedV3.requestBody), requestBefore);
  assert.equal(JSON.stringify(v3RequestBody), requestBefore, "no request rewriting");
  assert.equal(boundary.recordedModelInput(v3Detail, 5), null);
  for (const content of [
    {},
    { ...v3Context, observation: { ...v3Context.observation, image_not_sent_to_model: false } },
    { ...v3Context, observation: { ...v3Context.observation, accessibility_text: undefined } },
    { ...v3Context, next_step: "1" },
    { ...v3Context, remaining_actions: -1 },
  ]) {
    const malformed = structuredClone(v3RequestBody);
    malformed.messages[malformed.messages.length - 1].content = JSON.stringify(content);
    assert.equal(boundary.recordedModelInput(withRequest(malformed), 1), null);
  }
  assert.equal(
    boundary.recordedModelInput(detail, 5),
    null,
    "final capture must not be fabricated model input",
  );
  for (const mutation of [
    { task: { ...task, evaluation_only: false } },
    { task: { ...task, id: "other-task" } },
    { provenance: { evaluation_only: false, training_eligible: true } },
    { status: "imaginary" },
    { journal: [{ ...journal[1], attempt_id: "other" }] },
    {
      journal: [
        {
          ...journal[1],
          data: {
            step: 0,
            observation: { ...initial, image_not_sent_to_model: false },
          },
        },
      ],
    },
    {
      artifacts: [
        { ...artifacts[0], url: "https://outside.invalid/frame.png" },
      ],
    },
    {
      artifacts: [
        {
          ...artifacts[0],
          url: `/api/browser/attempts/${id}/artifacts/%2e%2e/private`,
        },
      ],
    },
    {
      artifacts: [
        {
          ...artifacts[0],
          url: "/api/browser/attempts/other/artifacts/frames/000.png",
        },
      ],
    },
  ])
    assert.equal(
      boundary.browserDetailSchema.safeParse({ ...detail, ...mutation })
        .success,
      false,
    );
  assert.equal(
    boundary.browserStatusSchema.safeParse({
      available: true,
      reason: null,
      active_attempts: 0,
      max_active_attempts: 1,
      providers: [],
      paid_calls_enabled: true,
    }).success,
    false,
  );
  for (const mutation of [
    { max_steps: 0 },
    { max_steps: 51 },
    { max_steps: 1.5 },
    { seed: -1 },
    { timeout_seconds: 29 },
    { timeout_seconds: 601 },
  ])
    assert.equal(
      boundary.browserConfigSchema.safeParse({ ...config, ...mutation })
        .success,
      false,
    );
  if (process.argv.includes("--schema-only")) {
    console.log(
      "Browser schema and recorded model-input boundaries passed; no browser or backend calls.",
    );
  } else {
    const { chromium } = require("playwright");
    await server.listen();
    const address = server.httpServer.address();
    assert.ok(address && typeof address !== "string");
    const base = `http://127.0.0.1:${address.port}`;
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 960 },
    });
    const errors = [];
    const posts = [];
    let current = structuredClone(detail);
    let ready = true;
    let failCreate = false;
    let failDetail = false;
    page.on("pageerror", (error) => errors.push(error.message));
    const status = () => ({
      available: ready,
      reason: ready ? null : "browser runtime not enabled",
      active_attempts: 0,
      max_active_attempts: 1,
      paid_calls_enabled: false,
      providers: [
        {
          id: "local-browser",
          name: "Local Browser",
          configured: ready,
          model: "qwen3:8b",
        },
        {
          id: "browser-reference",
          name: "Browser Reference Control",
          configured: ready,
          model: null,
        },
        {
          id: "browser-baseline",
          name: "Browser Incomplete Control",
          configured: ready,
          model: null,
        },
      ],
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      const reply = (json, code = 200) =>
        route.fulfill({
          status: code,
          contentType: "application/json",
          body: JSON.stringify(json),
        });
      if (url.pathname === "/api/health")
        return reply({
          status: "ok",
          version: "mock",
          execution: "in-process",
          active_runs: 0,
          paid_calls_enabled: false,
          max_global_concurrency: 8,
        });
      if (url.pathname === "/api/environments")
        return reply({ environments: [] });
      if (url.pathname === "/api/providers") return reply({ providers: [] });
      if (url.pathname === "/api/runs") return reply({ runs: [] });
      if (url.pathname === "/api/browser/tasks")
        return reply({ tasks: [task] });
      if (url.pathname === "/api/browser/status") return reply(status());
      if (
        url.pathname === "/api/browser/attempts" &&
        request.method() === "POST"
      ) {
        const body = request.postDataJSON();
        posts.push(body);
        if (failCreate)
          return reply({ detail: "browser admission limit reached" }, 409);
        current = {
          ...detail,
          config: body,
          status: "running",
          outcome: null,
          passed: false,
          reward: 0,
          cleanup: null,
        };
        const {
          journal: ignoredJournal,
          artifacts: ignoredArtifacts,
          ...created
        } = current;
        return reply(created, 202);
      }
      if (url.pathname === "/api/browser/attempts")
        return reply({ attempts: [summary] });
      if (url.pathname.endsWith("/cancel") && request.method() === "POST") {
        current = {
          ...current,
          status: "cancelled",
          termination: "cancelled",
          passed: false,
          reward: 0,
          cleanup: { status: "completed", error_code: null },
        };
        const {
          journal: ignoredJournal,
          artifacts: ignoredArtifacts,
          ...cancelled
        } = current;
        return reply(cancelled);
      }
      if (url.pathname.includes("/artifacts/"))
        return route.fulfill({
          contentType: "image/png",
          body: Buffer.from(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jY1sAAAAASUVORK5CYII=",
            "base64",
          ),
        });
      if (url.pathname === `/api/browser/attempts/${id}`)
        return failDetail
          ? reply({ detail: "browser evidence integrity check failed" }, 409)
          : reply(current);
      assert.fail(
        `Unexpected mock request: ${request.method()} ${url.pathname}`,
      );
    });
    await page.goto(`${base}/#browser-environments`);
    await page
      .getByRole("heading", { name: "Browser Environments", exact: true })
      .waitFor();
    await page.getByText("Browser runtime enabled", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "New attempt", exact: true })
      .click();
    await page
      .getByLabel("Browser model", { exact: true })
      .selectOption("qwen3:8b");
    const start = page.getByRole("button", {
      name: "Start attempt",
      exact: true,
    });
    await page.getByLabel("Max browser steps", { exact: true }).fill("0");
    await start.click();
    assert.equal(posts.length, 0);
    await page.getByLabel("Max browser steps", { exact: true }).fill("30");
    await page
      .getByLabel("Browser policy", { exact: true })
      .selectOption("browser-reference");
    await page
      .getByText("Scripted reference control. No model inference.", {
        exact: true,
      })
      .waitFor();
    await start.click();
    await page
      .getByRole("button", { name: "Cancel attempt", exact: true })
      .waitFor();
    assert.equal(posts.length, 1);
    assert.equal(posts[0].provider_id, "browser-reference");
    assert.equal("allow_paid" in posts[0], false);
    await page
      .getByRole("button", { name: "Cancel attempt", exact: true })
      .click();
    await page.getByText("cancelled", { exact: true }).first().waitFor();
    current = structuredClone(detail);
    await page.reload();
    await page
      .getByText("No model request recorded for this observation.", {
        exact: false,
      })
      .waitFor();
    await page
      .getByRole("button", {
        name: "Previous browser observation",
        exact: true,
      })
      .click();
    await page
      .getByText("Recorded model user context", { exact: false })
      .waitFor();
    const image = page.getByRole("img", {
      name: /Captured browser screen at event 1/,
    });
    assert.ok((await image.getAttribute("src")).endsWith("/frames/000.png"));
    current = structuredClone(v3Detail);
    await page.reload();
    await page
      .getByRole("button", { name: "Previous browser observation", exact: true })
      .click();
    const requestPanel = page.locator("details.browser-ax").filter({
      has: page.getByText("Recorded model request", { exact: false }),
    });
    await requestPanel.locator("summary").click();
    assert.deepEqual(
      JSON.parse(await requestPanel.locator("pre").innerText()),
      v3RequestBody,
      "render all recorded messages, tool calls, results and current context",
    );
    await page.getByRole("tab", { name: "Browser", exact: true }).focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(
      await page
        .getByRole("tab", { name: "Timeline", exact: true })
        .getAttribute("aria-selected"),
      "true",
    );
    await page.getByRole("button", { name: /action result/ }).click();
    await page
      .getByRole("heading", {
        name: "Recorded event / action result",
        exact: true,
      })
      .waitFor();
    await page.getByRole("tab", { name: "Outcome", exact: true }).click();
    await page
      .getByRole("heading", { name: "Independent verifier", exact: true })
      .waitFor();
    await page
      .getByText("Sealed application state confirms the requested change.", {
        exact: true,
      })
      .waitFor();
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`${base}/#attempts/${id}`);
      await page.getByRole("tab", { name: "Browser", exact: true }).click();
      const body = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      assert.ok(body.width <= body.viewport + 1, `body overflow at ${width}`);
      await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("link", { name: "Browser Environments", exact: true })
        .click();
      await page
        .getByRole("button", { name: "New attempt", exact: true })
        .click();
      const bounds = await page.getByRole("dialog").boundingBox();
      const footer = await start.boundingBox();
      assert.ok(
        bounds &&
          footer &&
          bounds.y >= 0 &&
          bounds.y + bounds.height <= 845 &&
          footer.y + footer.height <= 845,
        `dialog/footer containment at ${width}`,
      );
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    failCreate = true;
    await page
      .getByRole("button", { name: "New attempt", exact: true })
      .click();
    await start.click();
    await page
      .getByText("browser admission limit reached", { exact: true })
      .waitFor();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    ready = false;
    await page
      .getByRole("button", { name: "Refresh browser data", exact: true })
      .click();
    await page
      .getByText("Browser runtime unavailable", { exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "New attempt", exact: true })
        .isDisabled(),
      true,
    );
    failDetail = true;
    await page.goto(`${base}/#attempts/${id}`);
    await page
      .getByRole("heading", {
        name: "Attempt could not be loaded",
        exact: true,
      })
      .waitFor();
    assert.deepEqual(errors, []);
    console.log(
      "Browser console mock checks passed: schemas, distinct controls, create/cancel, exact AX input, timeline/outcome, unavailable/error states, 1440/390/360 containment. No backend or model calls.",
    );
  }
} finally {
  await browser?.close();
  await server.close();
}
