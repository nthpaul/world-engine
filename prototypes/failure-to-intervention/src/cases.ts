import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { TraceSchema, type Trace } from "./schemas";

export interface CaseFile {
  trace: Trace;
  path: string;
}

const DEFAULT_ROOT = fileURLToPath(new URL("..", import.meta.url));

export function loadCases(root: string = DEFAULT_ROOT): CaseFile[] {
  const paths = [join(root, "failure_trace.json")];
  const casesDir = join(root, "cases");
  for (const file of readdirSync(casesDir).filter((f) => f.endsWith(".json")).sort()) {
    paths.push(join(casesDir, file));
  }
  return paths.map((path) => ({
    trace: TraceSchema.parse(JSON.parse(readFileSync(path, "utf8"))),
    path,
  }));
}
