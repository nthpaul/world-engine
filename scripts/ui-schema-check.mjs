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
const server = await createServer({
  root: path.join(root, "web"),
  configFile: false,
  logLevel: "error",
  optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, watch: null },
});

try {
  // Use the production boundary schema compiled from api.ts, not a copied test schema.
  const { detailSchema } = await server.ssrLoadModule("/src/api.ts");
  const usageSchema = detailSchema.shape.episodes.element.shape.usage;
  const valid = [
    { input_tokens: 0, output_tokens: 7 },
    {
      recorded_decisions: 2,
      input_tokens_complete: true,
      output_tokens_complete: false,
      input_tokens: 0,
      output_tokens_known: 7,
      accounting_scope: "executed decisions only; failed request usage is unrecorded",
    },
    {
      request_attempts: 1,
      input_tokens_complete: false,
      output_tokens_complete: false,
      accounting_scope: "recorded transport attempts, not attested model executions",
    },
    {},
  ];
  for (const usage of valid) {
    const parsed = usageSchema.safeParse(usage);
    assert.ok(parsed.success, "episode usage must accept unknown metadata");
    assert.deepEqual(parsed.data, usage, "metadata must survive boundary validation");
  }
  assert.equal("input_tokens" in usageSchema.parse(valid[2]), false);
  for (const usage of [null, [], "unknown", 0, true, undefined]) {
    assert.equal(usageSchema.safeParse(usage).success, false, "usage must be an object");
  }
  console.log("Episode usage schema: 4 accepted metadata objects, 6 rejected non-objects; no inference or API calls.");
} finally {
  await server.close();
}
