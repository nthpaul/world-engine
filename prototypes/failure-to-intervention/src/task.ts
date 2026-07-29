import type { Trace } from "./schemas";

export interface Task {
  case_id: string;
  objective: string;
  constraints: string[];
  issued_at: string;
}

export function defineTask(trace: Trace): Task {
  return {
    case_id: trace.case_id,
    objective: trace.task.objective,
    constraints: [...trace.task.constraints],
    issued_at: trace.task.issued_at,
  };
}
