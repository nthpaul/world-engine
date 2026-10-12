import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Copy,
  FileText,
  GitBranch,
  LoaderCircle,
  Monitor,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Square,
  Terminal,
  X,
} from "lucide-react";
import {
  browserApi,
  browserObservationSchema,
  recordedModelInput,
  type BrowserAttempt,
  type BrowserConfig,
  type BrowserDetail,
  type BrowserJournalEntry,
  type BrowserStatus,
  type BrowserTask,
} from "./browserApi";

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Browser request failed.";
const seconds = (value: number) => `${value.toFixed(2)} s`;
const isActive = (attempt: BrowserAttempt) =>
  !["completed", "failed", "cancelled", "interrupted"].includes(attempt.status);
const providerLabel = (id: BrowserConfig["provider_id"]) =>
  id === "local-browser"
    ? "Local model"
    : id === "browser-reference"
      ? "Reference control"
      : "Baseline control";
const inspect = (id: string) => {
  window.location.hash = `attempts/${encodeURIComponent(id)}`;
};

function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <span />
      {value.replaceAll("_", " ")}
    </span>
  );
}
function Empty({
  title,
  text,
  loading = false,
}: {
  title: string;
  text: string;
  loading?: boolean;
}) {
  return (
    <div className="empty">
      {loading ? (
        <LoaderCircle size={26} className="spin" />
      ) : (
        <Monitor size={26} />
      )}
      <h2>{title}</h2>
      <p>{text}</p>
    </div>
  );
}
function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
function TaskIdentity({ task }: { task: BrowserTask }) {
  return (
    <dl className="browser-facts">
      <div>
        <dt>Application</dt>
        <dd>
          {task.application} / {task.application_version}
        </dd>
      </div>
      <div>
        <dt>Task version</dt>
        <dd>
          <code>
            {task.id} / {task.version}
          </code>
        </dd>
      </div>
      <div>
        <dt>Observation</dt>
        <dd>AX text / screenshots recorded separately</dd>
      </div>
      <div>
        <dt>Verifier</dt>
        <dd>
          <code>{task.grader_version}</code>
        </dd>
      </div>
      <div>
        <dt>Image digest</dt>
        <dd>
          <code>{task.image_digest}</code>
        </dd>
      </div>
      <div>
        <dt>Fixture hash</dt>
        <dd>
          <code>{task.fixture_hash}</code>
        </dd>
      </div>
    </dl>
  );
}

export default function BrowserConsole({
  view,
  attemptId,
  notify,
}: {
  view: "browser-environments" | "attempts";
  attemptId: string | null;
  notify: (message: string) => void;
}) {
  const [tasks, setTasks] = useState<BrowserTask[]>([]);
  const [status, setStatus] = useState<BrowserStatus | null>(null);
  const [attempts, setAttempts] = useState<BrowserAttempt[]>([]);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [launch, setLaunch] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [hasOlder, setHasOlder] = useState(false);
  useEffect(() => {
    let active = true;
    let pending = false;
    const controller = new AbortController();
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const [catalog, runtime, history] = await Promise.all([
          browserApi.tasks(controller.signal),
          browserApi.status(controller.signal),
          browserApi.attempts(controller.signal, historyOffset),
        ]);
        if (active) {
          setTasks(catalog.tasks);
          setStatus(runtime);
          setAttempts(history.attempts.slice(0, 25));
          setHasOlder(history.attempts.length > 25);
          setError("");
        }
      } catch (failure) {
        if (active) {
          setError(errorMessage(failure));
          setStatus(null);
        }
      } finally {
        pending = false;
        if (active) setLoaded(true);
      }
    };
    void load();
    const interval = setInterval(() => void load(), 2500);
    return () => {
      active = false;
      controller.abort();
      clearInterval(interval);
    };
  }, [revision, historyOffset]);
  const task = tasks.find((item) => item.id === selectedTask) ?? tasks[0];
  const canStart = Boolean(
    status?.available &&
    status.active_attempts < status.max_active_attempts &&
    status.providers.some((item) => item.configured) &&
    task,
  );
  if (attemptId && view === "attempts")
    return <AttemptInspector key={attemptId} id={attemptId} notify={notify} />;
  return (
    <section className="browser-console">
      <div className="page-heading">
        <div>
          <span className="eyebrow">REAL APPLICATIONS / EVALUATION ONLY</span>
          <h1>
            {view === "browser-environments"
              ? "Browser Environments"
              : "Attempts"}
          </h1>
          <p>
            Isolated application sessions, recorded browser evidence, and
            independent verification.
          </p>
        </div>
        <button
          className="button primary"
          disabled={!canStart}
          onClick={() => setLaunch(true)}
        >
          <Plus size={16} />
          New attempt
        </button>
      </div>
      <div className="browser-readiness" role="status">
        <Monitor size={18} />
        <strong>
          {status?.available
            ? "Browser runtime enabled"
            : loaded
              ? "Browser runtime unavailable"
              : "Connecting to browser runtime"}
        </strong>
        <span>
          {status?.available
            ? `${status.active_attempts} / ${status.max_active_attempts} active`
            : (status?.reason ?? error)}
        </span>
        <span className="browser-evaluation">
          <ShieldCheck size={14} />
          Evaluation only / no paid calls
        </span>
        <button
          className="icon-button"
          aria-label="Refresh browser data"
          title="Refresh browser data"
          onClick={() => setRevision((value) => value + 1)}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {error && (
        <div className="inline-error" role="alert">
          <CircleAlert size={16} />
          {error}
        </div>
      )}
      {!loaded ? (
        <Empty
          title="Loading browser environments"
          text="Retrieving tasks and runtime readiness."
          loading
        />
      ) : view === "browser-environments" ? (
        task ? (
          <div className="world-layout browser-world-layout">
            <div className="world-list">
              {tasks.map((item) => (
                <button
                  className={`world-item ${item.id === task.id ? "selected" : ""}`}
                  key={item.id}
                  onClick={() => setSelectedTask(item.id)}
                >
                  <Monitor size={19} />
                  <div>
                    <strong>{item.name}</strong>
                    <code>
                      {item.application} / v{item.version}
                    </code>
                  </div>
                  <ArrowRight size={16} />
                </button>
              ))}
            </div>
            <section className="world-detail">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">SEEDED TASK PACK</span>
                  <h2>{task.name}</h2>
                </div>
                <Status value="evaluation_only" />
              </div>
              <p className="browser-instruction">{task.instruction}</p>
              <TaskIdentity task={task} />
              <div className="browser-boundary">
                <ShieldCheck size={18} />
                <span>
                  Verifier state is sealed after the browser closes. Grader
                  fixtures and application credentials are not exposed to the
                  policy.
                </span>
              </div>
              <div className="section-heading">
                <h3>Execution policies</h3>
              </div>
              <p className="text-muted">
                Application and local model readiness are checked during attempt
                preparation.
              </p>
              {status?.providers.map((provider) => (
                <div className="browser-policy" key={provider.id}>
                  <div>
                    <strong>{providerLabel(provider.id)}</strong>
                    <small>
                      {provider.name}
                      {provider.id === "local-browser" && provider.model
                        ? ` / ${provider.model}`
                        : ""}
                    </small>
                  </div>
                  <Status value={provider.configured ? "enabled" : "offline"} />
                </div>
              ))}
            </section>
          </div>
        ) : (
          <Empty
            title="No browser task packs"
            text="No real-application task packs are registered in this runtime."
          />
        )
      ) : (
        <>
          <div className="section-heading">
            <h2>
              Browser attempt history <span>{attempts.length} loaded</span>
            </h2>
            <a className="button quiet" href="#browser-environments">
              <Monitor size={15} />
              Environments
            </a>
          </div>
          <nav className="history-pager" aria-label="Browser attempt pages">
            <span>Page {historyOffset / 25 + 1}</span>
            <div>
              <button
                className="icon-button"
                aria-label="Newer browser attempts"
                title="Newer browser attempts"
                disabled={!historyOffset}
                onClick={() =>
                  setHistoryOffset((value) => Math.max(0, value - 25))
                }
              >
                <ArrowLeft size={16} />
              </button>
              <button
                className="icon-button"
                aria-label="Older browser attempts"
                title="Older browser attempts"
                disabled={!hasOlder || historyOffset >= 100000}
                onClick={() => setHistoryOffset((value) => value + 25)}
              >
                <ArrowRight size={16} />
              </button>
            </div>
          </nav>
          {attempts.length ? (
            <div className="table-scroll">
              <table aria-label="Browser attempts">
                <thead>
                  <tr>
                    <th>Task / attempt</th>
                    <th>Policy</th>
                    <th>Lifecycle</th>
                    <th>Verifier outcome</th>
                    <th>Steps</th>
                    <th>Elapsed</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {attempts.map((attempt) => (
                    <tr key={attempt.id}>
                      <td>
                        <a
                          className="run-link"
                          href={`#attempts/${encodeURIComponent(attempt.id)}`}
                        >
                          {attempt.task.name}
                        </a>
                        <code>
                          {attempt.id.slice(0, 12)} / seed {attempt.config.seed}
                        </code>
                      </td>
                      <td>
                        {providerLabel(attempt.config.provider_id)}
                        <small>
                          {attempt.config.provider_id === "local-browser"
                            ? attempt.config.model
                            : "Scripted control / no model inference"}
                        </small>
                      </td>
                      <td>
                        <Status value={attempt.status} />
                      </td>
                      <td>
                        {attempt.outcome ? (
                          <Status
                            value={attempt.outcome.passed ? "passed" : "failed"}
                          />
                        ) : (
                          <span className="text-muted">Not graded</span>
                        )}
                      </td>
                      <td>
                        {attempt.steps}
                        <small>{attempt.invalid_actions} invalid actions</small>
                      </td>
                      <td>{seconds(attempt.elapsed_seconds)}</td>
                      <td>{new Date(attempt.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="No browser attempts yet"
              text="A task pack and a ready policy are required to start an isolated session."
            />
          )}
        </>
      )}
      {launch && task && status && (
        <StartAttempt
          tasks={tasks}
          initialTask={task.id}
          status={status}
          close={() => setLaunch(false)}
          created={(attempt) => {
            setLaunch(false);
            notify("Browser attempt created.");
            inspect(attempt.id);
          }}
        />
      )}
    </section>
  );
}

function StartAttempt({
  tasks,
  initialTask,
  status,
  close,
  created,
}: {
  tasks: BrowserTask[];
  initialTask: string;
  status: BrowserStatus;
  close: () => void;
  created: (attempt: BrowserAttempt) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const initialProvider =
    status.providers.find(
      (item) => item.configured && item.id === "local-browser",
    ) ?? status.providers.find((item) => item.configured);
  const [config, setConfig] = useState<BrowserConfig>({
    task_id: initialTask,
    provider_id: initialProvider?.id ?? "local-browser",
    model: initialProvider?.model ?? "qwen3:8b",
    seed: 42,
    max_steps: 30,
    timeout_seconds: 180,
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const provider = status.providers.find(
    (item) => item.id === config.provider_id,
  );
  const models = provider?.models ?? (provider?.model ? [provider.model] : []);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError("");
    try {
      created(await browserApi.create(config));
    } catch (failure) {
      setError(errorMessage(failure));
      setPending(false);
    }
  };
  return (
    <dialog
      ref={dialog}
      className="launch-dialog browser-launch"
      aria-labelledby="browser-launch-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) close();
      }}
    >
      <form onSubmit={(event) => void submit(event)}>
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">ISOLATED BROWSER SESSION</span>
            <h2 id="browser-launch-title">New browser attempt</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            title="Close dialog"
            aria-label="Close browser attempt dialog"
            disabled={pending}
            onClick={close}
          >
            <X size={18} />
          </button>
        </div>
        <div className="dialog-body">
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <label>
            Task pack
            <select
              aria-label="Browser task"
              value={config.task_id}
              onChange={(event) =>
                setConfig({ ...config, task_id: event.target.value })
              }
            >
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Policy
            <select
              aria-label="Browser policy"
              value={config.provider_id}
              onChange={(event) => {
                const next = status.providers.find(
                  (item) => item.id === event.target.value,
                );
                if (next)
                  setConfig({
                    ...config,
                    provider_id: next.id,
                    model: next.model ?? "qwen3:8b",
                  });
              }}
            >
              {status.providers.map((item) => (
                <option
                  key={item.id}
                  value={item.id}
                  disabled={!item.configured}
                >
                  {providerLabel(item.id)}
                  {item.configured ? "" : " (unavailable)"}
                </option>
              ))}
            </select>
          </label>
          {config.provider_id === "local-browser" ? (
            <label>
              Local model
              <select
                aria-label="Browser model"
                value={config.model}
                disabled={!models.length}
                onChange={(event) =>
                  setConfig({ ...config, model: event.target.value })
                }
              >
                {models.map((model) => (
                  <option key={model}>{model}</option>
                ))}
              </select>
            </label>
          ) : (
            <p className="field-note">
              Scripted{" "}
              {config.provider_id === "browser-reference"
                ? "reference"
                : "baseline"}{" "}
              control. No model inference.
            </p>
          )}
          <div className="form-grid">
            {(
              [
                { key: "seed", label: "Seed", min: 0, max: 2147483647 },
                {
                  key: "max_steps",
                  label: "Max browser steps",
                  min: 1,
                  max: 50,
                },
                {
                  key: "timeout_seconds",
                  label: "Interaction timeout (s)",
                  min: 30,
                  max: 600,
                },
              ] satisfies {
                key: "seed" | "max_steps" | "timeout_seconds";
                label: string;
                min: number;
                max: number;
              }[]
            ).map((field) => (
              <label key={field.key}>
                {field.label}
                <input
                  aria-label={field.label}
                  type="number"
                  step={1}
                  min={field.min}
                  max={field.max}
                  required
                  value={config[field.key]}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      [field.key]: Number(event.target.value),
                    })
                  }
                />
              </label>
            ))}
          </div>
          <label className="evaluation-consent">
            <input type="checkbox" checked disabled />
            <span>Evaluation only / paid model calls disabled</span>
          </label>
        </div>
        <div className="dialog-footer">
          <span>
            <Monitor size={14} />
            One active sandbox
          </span>
          <button
            type="button"
            className="button quiet"
            disabled={pending}
            onClick={close}
          >
            Cancel
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={
              pending ||
              !provider?.configured ||
              !status.available ||
              status.active_attempts >= status.max_active_attempts
            }
          >
            {pending ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <Play size={15} />
            )}
            {pending ? "Creating..." : "Start attempt"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function ObservationPane({
  attempt,
  entry,
}: {
  attempt: BrowserDetail;
  entry: BrowserJournalEntry | undefined;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const parsed = browserObservationSchema.safeParse(entry?.data.observation);
  const observation = parsed.success ? parsed.data : null;
  const artifact = attempt.artifacts.find(
    (item) =>
      item.kind === "screenshot" &&
      item.id === observation?.screenshot_artifact_id,
  );
  const modelInput = entry ? recordedModelInput(attempt, entry.sequence) : null;
  useEffect(() => setImageFailed(false), [artifact?.id]);
  if (!observation)
    return (
      <Empty
        title="No recorded browser observation"
        text="Screenshots and AX observations appear after the browser starts."
      />
    );
  return (
    <section
      className="browser-observation"
      aria-label="Recorded browser observation"
    >
      <div className="browser-location">
        <Monitor size={15} />
        <strong>{observation.title || "Untitled page"}</strong>
        <code>{observation.url}</code>
      </div>
      <div className="browser-screen">
        {artifact && !imageFailed ? (
          <a
            href={artifact.url}
            target="_blank"
            rel="noopener noreferrer"
            title="Open original captured screenshot"
          >
            <img
              src={artifact.url}
              alt={`Captured browser screen at event ${entry?.sequence}: ${observation.title}`}
              onError={() => setImageFailed(true)}
            />
          </a>
        ) : (
          <Empty
            title="Screenshot unavailable"
            text="No readable screenshot artifact was returned for this observation."
          />
        )}
      </div>
      <div className="browser-observation-label">
        <span>Captured screenshot / operator evidence</span>
        <strong>Image not sent to model</strong>
      </div>
      <details className="browser-ax" open>
        <summary>
          <FileText size={15} />
          Recorded AX text <span>Event {entry?.sequence}</span>
        </summary>
        <pre>{observation.accessibility_text}</pre>
      </details>
      {modelInput ? (
        <details className="browser-ax">
          <summary>
            <FileText size={15} />
            {modelInput.kind === "v3"
              ? "Recorded model request"
              : "Recorded model user context"}{" "}
            <span>
              {modelInput.observation.accessibility_truncated
                ? "AX truncated"
                : "AX untruncated"}
            </span>
          </summary>
          <Json
            value={
              modelInput.kind === "v3"
                ? modelInput.requestBody
                : modelInput.context
            }
          />
        </details>
      ) : (
        <p className="browser-no-model-input">
          No model request recorded for this observation. Controls and final
          captures do not imply model input.
        </p>
      )}
    </section>
  );
}

function AttemptInspector({
  id,
  notify,
}: {
  id: string;
  notify: (message: string) => void;
}) {
  const [attempt, setAttempt] = useState<BrowserDetail | null>(null);
  const [error, setError] = useState("");
  const [selectedSequence, setSelectedSequence] = useState<number | null>(null);
  const [tab, setTab] = useState<"browser" | "timeline" | "outcome">("browser");
  const [cancelling, setCancelling] = useState(false);
  useEffect(() => {
    let active = true;
    let pending = false;
    let terminal = false;
    const controller = new AbortController();
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const detail = await browserApi.attempt(id, controller.signal);
        terminal = !isActive(detail);
        if (active) {
          setAttempt(detail);
          setError("");
        }
      } catch (failure) {
        if (active) setError(errorMessage(failure));
      } finally {
        pending = false;
      }
    };
    void load();
    const interval = setInterval(() => {
      if (!terminal) void load();
    }, 1500);
    return () => {
      active = false;
      controller.abort();
      clearInterval(interval);
    };
  }, [id]);
  const cancel = async () => {
    setCancelling(true);
    try {
      await browserApi.cancel(id);
      notify("Browser cancellation requested.");
      setAttempt(await browserApi.attempt(id));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setCancelling(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      notify("Attempt ID copied.");
    } catch {
      notify("Clipboard permission unavailable.");
    }
  };
  if (!attempt)
    return (
      <>
        <a className="back-link" href="#attempts">
          <ArrowLeft size={15} />
          Browser attempts
        </a>
        <Empty
          title={
            error ? "Attempt could not be loaded" : "Loading browser attempt"
          }
          text={
            error || "Retrieving captured observations and verifier outcome."
          }
          loading={!error}
        />
      </>
    );
  const observations = attempt.journal.filter(
    (item) => item.event === "observation",
  );
  const selected =
    attempt.journal.find((item) => item.sequence === selectedSequence) ??
    observations.at(-1) ??
    attempt.journal.at(-1);
  const observation = observations
    .filter((item) => item.sequence <= (selected?.sequence ?? Infinity))
    .at(-1);
  const observationIndex = observations.findIndex(
    (item) => item.sequence === observation?.sequence,
  );
  const video = attempt.artifacts.find((item) => item.kind === "video");
  const trace = attempt.artifacts.find((item) => item.kind === "public_trace");
  return (
    <section className="browser-console">
      <a className="back-link" href="#attempts">
        <ArrowLeft size={15} />
        Browser attempts
      </a>
      <div className="page-heading detail-heading">
        <div>
          <span className="eyebrow">
            BROWSER ATTEMPT / {attempt.task.application}
          </span>
          <h1>{attempt.task.name}</h1>
          <div className="detail-subtitle">
            <code>{attempt.id}</code>
            <button
              className="icon-button small"
              aria-label="Copy attempt ID"
              title="Copy attempt ID"
              onClick={() => void copy()}
            >
              <Copy size={14} />
            </button>
            <Status value={attempt.status} />
          </div>
        </div>
        {isActive(attempt) && (
          <button
            className="button danger"
            disabled={cancelling}
            onClick={() => void cancel()}
          >
            <Square size={15} />
            {cancelling ? "Cancelling..." : "Cancel attempt"}
          </button>
        )}
      </div>
      {(error || attempt.error) && (
        <div className="inline-error" role="alert">
          <CircleAlert size={16} />
          {error || attempt.error}
        </div>
      )}
      {(attempt.reconciliation_required ||
        attempt.journal_finalization_failed) && (
        <div className="inline-error" role="alert">
          <ShieldCheck size={16} />
          {attempt.journal_finalization_failed
            ? "Journal finalization failed; this evidence may be incomplete."
            : "Resource reconciliation required; new browser admission is blocked."}
        </div>
      )}
      <div className="metric-strip browser-metrics">
        <div className="metric">
          <span>Verifier outcome</span>
          <strong>
            {attempt.outcome
              ? attempt.outcome.passed
                ? "Passed"
                : "Failed"
              : "Not graded"}
          </strong>
          <small>Independent sealed-state verifier</small>
        </div>
        <div className="metric">
          <span>Browser steps</span>
          <strong>
            {attempt.steps} / {attempt.config.max_steps}
          </strong>
          <small>{attempt.invalid_actions} invalid actions</small>
        </div>
        <div className="metric">
          <span>Elapsed</span>
          <strong>{seconds(attempt.elapsed_seconds)}</strong>
          <small>
            {attempt.config.timeout_seconds} s interaction bound; startup and
            finalization separate
          </small>
        </div>
        <div className="metric">
          <span>Cleanup</span>
          <strong>{attempt.cleanup?.status ?? "Pending"}</strong>
          <small>Separate from task outcome</small>
        </div>
      </div>
      <div className="run-config-bar">
        <span>
          <Monitor size={15} />
          {providerLabel(attempt.config.provider_id)}
          {attempt.config.provider_id === "local-browser"
            ? ` / ${attempt.config.model}`
            : " / no inference"}
        </span>
        <span>
          <GitBranch size={15} />
          Seed {attempt.config.seed}
        </span>
        <span>
          <ShieldCheck size={15} />
          Evaluation only / AX observations
        </span>
      </div>
      <div className="detail-toolbar">
        <div className="tabs" role="tablist" aria-label="Browser attempt views">
          {(
            [
              { id: "browser", label: "Browser", icon: Monitor },
              { id: "timeline", label: "Timeline", icon: Activity },
              { id: "outcome", label: "Outcome", icon: ShieldCheck },
            ] satisfies {
              id: typeof tab;
              label: string;
              icon: typeof Monitor;
            }[]
          ).map((item) => (
            <button
              key={item.id}
              role="tab"
              id={`browser-tab-${item.id}`}
              aria-controls="browser-attempt-panel"
              aria-selected={tab === item.id}
              tabIndex={tab === item.id ? 0 : -1}
              className={tab === item.id ? "selected" : ""}
              onClick={() => setTab(item.id)}
              onKeyDown={(event) => {
                const direction =
                  event.key === "ArrowRight"
                    ? 1
                    : event.key === "ArrowLeft"
                      ? -1
                      : 0;
                if (!direction) return;
                event.preventDefault();
                const tabs = [
                  "browser",
                  "timeline",
                  "outcome",
                ] satisfies (typeof tab)[];
                const next =
                  tabs[
                    (tabs.indexOf(item.id) + direction + tabs.length) %
                      tabs.length
                  ];
                setTab(next);
                document.getElementById(`browser-tab-${next}`)?.focus();
              }}
            >
              <item.icon size={15} />
              {item.label}
            </button>
          ))}
        </div>
        {trace && (
          <a className="button quiet" href={trace.url} download>
            <ArrowDownToLine size={15} />
            Public trace
          </a>
        )}
      </div>
      <div
        id="browser-attempt-panel"
        role="tabpanel"
        aria-labelledby={`browser-tab-${tab}`}
      >
        {tab === "outcome" ? (
          <div className="browser-outcome">
            <div className="section-heading">
              <h2>Independent verifier</h2>
              <Status
                value={
                  attempt.outcome
                    ? attempt.outcome.passed
                      ? "passed"
                      : "failed"
                    : "not_graded"
                }
              />
            </div>
            {attempt.outcome ? (
              <>
                <p className="text-muted">
                  Grade recorded after browser closure and state sealing.
                </p>
                <div className="grader-checks">
                  {attempt.outcome.checks.map((check) => (
                    <div className="grader-check" key={check.name}>
                      {check.passed ? (
                        <CheckCircle2 size={18} />
                      ) : (
                        <CircleAlert size={18} />
                      )}
                      <div>
                        <h3>{check.name}</h3>
                        <p>{check.detail}</p>
                      </div>
                      <Status value={check.passed ? "passed" : "failed"} />
                    </div>
                  ))}
                </div>
                <dl className="browser-facts">
                  <div>
                    <dt>Reward</dt>
                    <dd>{attempt.outcome.reward}</dd>
                  </div>
                  <div>
                    <dt>Grader version</dt>
                    <dd>{attempt.outcome.grader_version}</dd>
                  </div>
                  <div>
                    <dt>Sealed state hash</dt>
                    <dd>
                      <code>{attempt.outcome.sealed_state_sha256}</code>
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              <Empty
                title="No verifier outcome"
                text="An execution status is not a task grade. The verifier may be pending or execution may have ended before grading."
              />
            )}
            <div className="section-heading">
              <h2>Lifecycle and provenance</h2>
            </div>
            <TaskIdentity task={attempt.task} />
            <details>
              <summary>Configuration, phase timings and cleanup</summary>
              <Json
                value={{
                  termination: attempt.termination,
                  passed: attempt.passed,
                  reward: attempt.reward,
                  reconciliation_required: attempt.reconciliation_required,
                  journal_finalization_failed:
                    attempt.journal_finalization_failed,
                  config: attempt.config,
                  phase_seconds: attempt.phase_seconds,
                  cleanup: attempt.cleanup,
                  provenance: attempt.provenance,
                }}
              />
            </details>
          </div>
        ) : (
          <>
            <div className="browser-step-controls">
              <span>
                Observation {observationIndex >= 0 ? observationIndex + 1 : 0} /{" "}
                {observations.length}
                {selected && (
                  <small>
                    {" "}
                    / event {selected.sequence}:{" "}
                    {selected.event.replaceAll("_", " ")}
                  </small>
                )}
              </span>
              <div>
                <button
                  className="icon-button"
                  title="Previous observation"
                  aria-label="Previous browser observation"
                  disabled={observationIndex <= 0}
                  onClick={() =>
                    setSelectedSequence(
                      observations[observationIndex - 1]?.sequence ?? null,
                    )
                  }
                >
                  <ArrowLeft size={16} />
                </button>
                <button
                  className="icon-button"
                  title="Next observation"
                  aria-label="Next browser observation"
                  disabled={
                    observationIndex < 0 ||
                    observationIndex >= observations.length - 1
                  }
                  onClick={() =>
                    setSelectedSequence(
                      observations[observationIndex + 1]?.sequence ?? null,
                    )
                  }
                >
                  <ArrowRight size={16} />
                </button>
              </div>
            </div>
            <div className="browser-evidence-layout">
              <div
                className="browser-event-list"
                aria-label="Browser event timeline"
              >
                {attempt.journal.map((entry) => (
                  <button
                    className={`browser-event ${selected?.sequence === entry.sequence ? "selected" : ""}`}
                    key={entry.sequence}
                    onClick={() => setSelectedSequence(entry.sequence)}
                  >
                    <code>{String(entry.sequence).padStart(2, "0")}</code>
                    <div>
                      <strong>{entry.event.replaceAll("_", " ")}</strong>
                      <small>{new Date(entry.at).toLocaleTimeString()}</small>
                    </div>
                    {entry.event === "observation" ? (
                      <Monitor size={14} />
                    ) : entry.event === "graded" ? (
                      <ShieldCheck size={14} />
                    ) : (
                      <Activity size={14} />
                    )}
                  </button>
                ))}
              </div>
              <div className="browser-evidence-main">
                <ObservationPane attempt={attempt} entry={observation} />
                {tab === "timeline" && selected && (
                  <section className="browser-event-data">
                    <h3>
                      Recorded event / {selected.event.replaceAll("_", " ")}
                    </h3>
                    <Json value={selected.data} />
                  </section>
                )}
              </div>
            </div>
            {video && (
              <section className="browser-video">
                <div className="section-heading">
                  <h2>Full-session recording</h2>
                  <a className="button quiet" href={video.url} download>
                    <ArrowDownToLine size={15} />
                    Video
                  </a>
                </div>
                <video
                  controls
                  preload="metadata"
                  src={video.url}
                  aria-label="Recorded browser session"
                />
                <p className="text-muted">
                  The selected timeline event controls the captured screenshot.
                  Video is the full session; per-step video offsets are not
                  recorded.
                </p>
              </section>
            )}
            <div className="browser-unavailable">
              <span>
                <Terminal size={15} />
                Terminal unavailable in this browser-only task pack
              </span>
              <span>
                <FileText size={15} />
                Agent file workspace unavailable
              </span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
