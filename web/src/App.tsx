import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Box,
  CheckCircle2,
  ChevronsLeft,
  ChevronRight,
  Circle,
  CircleAlert,
  Copy,
  FlaskConical,
  GitBranch,
  Layers3,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  Settings2,
  Square,
  Terminal,
  X,
} from "lucide-react";
import {
  api,
  type Environment,
  type Episode,
  type ExportFormat,
  type Health,
  type Provider,
  type Run,
  type RunConfig,
  type RunDetail,
} from "./api";

type View = "runs" | "worlds" | "benchmarks" | "runtime";
type Route = { view: View; runId: string | null };
const navigation = [
  { id: "runs", label: "Rollout runs", icon: Activity },
  { id: "worlds", label: "World library", icon: Box },
  { id: "benchmarks", label: "Benchmarks", icon: FlaskConical },
  { id: "runtime", label: "Runtime", icon: Server },
] satisfies { id: View; label: string; icon: typeof Activity }[];
const live = (run: Run) => run.status === "queued" || run.status === "running";
const HISTORY_PAGE_SIZE = 50;
const HISTORY_MAX_OFFSET = 100000;
const percent = (value: number) => `${Math.round(value * 100)}%`;
const number = (value: number) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
const duration = (value: number) =>
  value < 1 ? `${Math.round(value * 1000)} ms` : `${number(value)} s`;
const message = (error: unknown) =>
  error instanceof Error ? error.message : "The request failed.";
const runName = (run: Run) =>
  run.label || `${run.config.environment_id} / ${run.config.provider_id}`;
const defaultModel = (provider: Provider | undefined) =>
  provider?.kind === "local"
    ? (provider.models.find((model) => model === "qwen3:8b") ?? null)
    : (provider?.models[0] ?? null);

function readRoute(): Route {
  const parts = window.location.hash.slice(1).split("/");
  const view = navigation.find((item) => item.id === parts[0])?.id ?? "runs";
  return {
    view,
    runId: view === "runs" && parts[1] ? decodeURIComponent(parts[1]) : null,
  };
}
function go(view: View, runId?: string) {
  window.location.hash = runId ? `${view}/${encodeURIComponent(runId)}` : view;
}

export default function App() {
  const [route, setRoute] = useState(readRoute);
  const [health, setHealth] = useState<Health | null>(null);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [hasOlder, setHasOlder] = useState(false);
  const historyRequest = useRef(0);
  const historyPendingOffset = useRef<number | null>(null);
  const historyController = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [launch, setLaunch] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [selectedSnapshots, setSelectedSnapshots] = useState<Run[]>([]);
  const refreshHistory = useCallback(async () => {
    if (historyPendingOffset.current === historyOffset) return;
    const request = ++historyRequest.current;
    historyPendingOffset.current = historyOffset;
    historyController.current?.abort();
    const controller = new AbortController();
    historyController.current = controller;
    try {
      const result = await api.runs({
        limit: HISTORY_PAGE_SIZE + 1,
        offset: historyOffset,
        signal: controller.signal,
      });
      if (request !== historyRequest.current) return;
      setRuns(result.runs.slice(0, HISTORY_PAGE_SIZE));
      setHasOlder(result.runs.length > HISTORY_PAGE_SIZE);
      setHistoryError("");
    } catch (err) {
      if (request === historyRequest.current) setHistoryError(message(err));
    } finally {
      if (request === historyRequest.current) {
        historyPendingOffset.current = null;
        historyController.current = null;
        setHistoryLoading(false);
      }
    }
  }, [historyOffset]);
  const refresh = useCallback(async () => {
    try {
      const [h, e, p] = await Promise.all([
        api.health(),
        api.environments(),
        api.providers(),
        refreshHistory(),
      ]);
      setHealth(h);
      setEnvironments(e.environments);
      setProviders(p.providers);
      setError("");
    } catch (err) {
      setError(message(err));
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, [refreshHistory]);
  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 2000);
    return () => {
      clearInterval(interval);
      historyRequest.current += 1;
      historyController.current?.abort();
      historyController.current = null;
      historyPendingOffset.current = null;
    };
  }, [refresh]);
  useEffect(() => {
    const change = () => setRoute(readRoute());
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  const completed = runs.filter((run) => run.status === "completed");
  const comparisonRuns = [
    ...runs,
    ...selectedSnapshots.filter((saved) => !runs.some((run) => run.id === saved.id)),
  ];
  const selectComparedRuns = (ids: string[]) => {
    setSelectedRuns(ids);
    setSelectedSnapshots(comparisonRuns.filter((run) => ids.includes(run.id)));
  };
  useEffect(() => {
    setSelectedSnapshots((saved) =>
      saved.map((run) => runs.find((current) => current.id === run.id) ?? run),
    );
  }, [runs]);
  const changeHistoryPage = (offset: number) => {
    historyRequest.current += 1;
    historyController.current?.abort();
    historyController.current = null;
    historyPendingOffset.current = null;
    setHistoryLoading(true);
    setHistoryError("");
    setRuns([]);
    setHasOlder(false);
    setHistoryOffset(offset);
  };
  const episodes = runs.reduce(
    (total, run) => total + run.completed_episodes,
    0,
  );
  const passed = runs.reduce((total, run) => total + run.passed_episodes, 0);
  const filtered = runs.filter(
    (run) =>
      (statusFilter === "all" || run.status === statusFilter) &&
      `${runName(run)} ${run.id} ${run.config.model ?? ""}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const title =
    navigation.find((item) => item.id === route.view)?.label ?? "Rollout runs";
  const cancel = async (id: string) => {
    try {
      await api.cancel(id);
      setNotice("Cancellation requested.");
      await refresh();
    } catch (err) {
      setNotice(message(err));
    }
  };
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#runs">
          <Layers3 size={25} strokeWidth={1.8} />
          <span>
            World Engine<small>Research console</small>
          </span>
        </a>
        <div className="workspace-label">
          WORKSPACE <span>LOCAL</span>
        </div>
        <nav aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <a
              key={id}
              href={`#${id}`}
              className={route.view === id ? "nav-item active" : "nav-item"}
              aria-current={route.view === id ? "page" : undefined}
            >
              <Icon size={18} />
              <span>{label}</span>
              {id === "runs" && health && health.active_runs > 0 && (
                <span className="nav-count" title="Active runs across the runtime">
                  {health.active_runs}
                </span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="runtime-light">
            <span className={`connection-dot ${health ? "online" : ""}`} />
            {health ? "Runtime connected" : "Runtime offline"}
          </div>
          <code>127.0.0.1:8000</code>
          <small>
            {health
              ? `v${health.version} / ${health.execution}`
              : "Waiting for local API"}
          </small>
        </div>
      </aside>
      <div className="content-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />
            <span>{title}</span>
          </div>
          <div className="topbar-actions">
            <span className="local-tag">
              <Circle size={8} fill="currentColor" />
              Local execution
            </span>
            <button
              className="icon-button"
              title="Refresh runtime data"
              aria-label="Refresh runtime data"
              onClick={() => void refresh()}
            >
              <RefreshCw size={17} />
            </button>
          </div>
        </header>
        <main>
          {error && (
            <div role="alert" className="error-banner">
              <CircleAlert size={18} />
              <div>
                <strong>Runtime unavailable</strong>
                <span>{error}</span>
              </div>
              <button className="button quiet" onClick={() => void refresh()}>
                <RefreshCw size={15} />
                Retry
              </button>
            </div>
          )}
          {notice && (
            <div className="toast" role="status">
              <CheckCircle2 size={17} />
              {notice}
              <button
                title="Dismiss notification"
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {route.view === "runs" && route.runId ? (
            <RunInspector
              id={route.runId}
              environments={environments}
              notify={setNotice}
              cancel={cancel}
            />
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    {route.view === "runs"
                      ? "EXECUTION"
                      : route.view === "worlds"
                        ? "ENVIRONMENTS"
                        : route.view === "benchmarks"
                          ? "EVALUATION"
                          : "CONFIGURATION"}
                  </div>
                  <h1>{title}</h1>
                  <p>
                    {route.view === "runs"
                      ? "Episode batches, outcomes, and reproducible agent traces."
                      : route.view === "worlds"
                        ? "Stateful workflow environments and their tool contracts."
                        : route.view === "benchmarks"
                          ? "Compare observed outcomes across runs and model providers."
                          : "Provider configuration and local execution readiness."}
                  </p>
                </div>
                {route.view !== "runtime" && (
                  <button
                    className="button primary"
                    onClick={() => setLaunch("")}
                    disabled={!health || !environments.length}
                  >
                    <Plus size={17} />
                    New rollout
                  </button>
                )}
              </div>
              {loading ? (
                <Empty
                  icon={LoaderCircle}
                  title="Connecting to runtime"
                  text="Loading environments, providers, and rollout history."
                />
              ) : route.view === "runs" ? (
                <>
                  <div className="metric-strip">
                    <Metric
                      label="Runs on page"
                      value={String(runs.length)}
                      note={`${runs.filter(live).length} active on page`}
                    />
                    <Metric
                      label="Page episodes"
                      value={number(episodes)}
                      note={`${completed.length} completed batches on page`}
                    />
                    <Metric
                      label="Page pass rate"
                      value={episodes ? percent(passed / episodes) : "--"}
                      note={`${passed} page episodes passed`}
                    />
                    <Metric
                      label="Worlds available"
                      value={String(environments.length)}
                      note="Deterministic, seeded workflows"
                    />
                  </div>
                  <div className="section-heading">
                    <h2>
                      Run history <span>{filtered.length} on page</span>
                    </h2>
                    <div className="table-tools">
                      <label className="search">
                        <Search size={16} />
                        <input
                          placeholder="Search this page..."
                          value={query}
                          onChange={(event) => setQuery(event.target.value)}
                          aria-label="Search runs on this page"
                        />
                      </label>
                      <select
                        aria-label="Filter run status on this page"
                        value={statusFilter}
                        onChange={(event) =>
                          setStatusFilter(event.target.value)
                        }
                      >
                        <option value="all">All statuses</option>
                        {[
                          "running",
                          "queued",
                          "completed",
                          "cancelled",
                          "failed",
                          "interrupted",
                        ].map((status) => (
                          <option key={status}>{status}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <HistoryPager
                    offset={historyOffset}
                    count={runs.length}
                    hasOlder={hasOlder}
                    loading={historyLoading}
                    change={changeHistoryPage}
                  />
                  {historyError && (
                    <div className="history-error" role="alert">
                      <CircleAlert size={16} />
                      <span>History refresh failed: {historyError}</span>
                      <button className="button quiet" onClick={() => {
                        setHistoryLoading(true);
                        void refreshHistory();
                      }}>
                        <RefreshCw size={14} />Retry history
                      </button>
                    </div>
                  )}
                  {historyLoading ? (
                    <Empty
                      icon={LoaderCircle}
                      title="Loading run page"
                      text={`Page ${historyOffset / HISTORY_PAGE_SIZE + 1}`}
                    />
                  ) : runs.length ? (
                    filtered.length ? (
                      <div className="table-scroll">
                        <table className="run-table">
                          <thead>
                            <tr>
                              <th>Run / environment</th>
                              <th>Provider</th>
                              <th>Status</th>
                              <th>Episodes</th>
                              <th>Pass rate</th>
                              <th>Reward</th>
                              <th>Created</th>
                              <th aria-label="Actions" />
                            </tr>
                          </thead>
                          <tbody>
                            {filtered.map((run) => (
                              <tr key={run.id}>
                                <td>
                                  <a
                                    className="run-link"
                                    href={`#runs/${run.id}`}
                                  >
                                    {run.label || run.config.environment_id}
                                  </a>
                                  <code>
                                    {run.id.slice(0, 12)}{" "}
                                    <span className="text-muted">
                                      / seed {run.config.seed}
                                    </span>
                                  </code>
                                </td>
                                <td>
                                  <span>{run.config.provider_id}</span>
                                  <small>
                                    {run.config.model || "Built-in policy"}
                                  </small>
                                </td>
                                <td>
                                  <Status value={run.status} />
                                </td>
                                <td>
                                  <span>
                                    {run.completed_episodes}{" "}
                                    <span className="text-muted">
                                      / {run.total_episodes}
                                    </span>
                                  </span>
                                  <progress
                                    max={run.total_episodes}
                                    value={run.completed_episodes}
                                    aria-label={`${run.completed_episodes} of ${run.total_episodes} episodes`}
                                  />
                                </td>
                                <td>
                                  <span
                                    className={
                                      run.success_rate > 0.8 ? "good-text" : ""
                                    }
                                  >
                                    {percent(run.success_rate)}
                                  </span>
                                </td>
                                <td className="numeric">
                                  {number(run.mean_reward)}
                                </td>
                                <td>
                                  <span>
                                    {new Date(
                                      run.created_at,
                                    ).toLocaleDateString(undefined, {
                                      month: "short",
                                      day: "numeric",
                                    })}
                                  </span>
                                  <small>
                                    {new Date(
                                      run.created_at,
                                    ).toLocaleTimeString(undefined, {
                                      hour: "2-digit",
                                      minute: "2-digit",
                                    })}
                                  </small>
                                </td>
                                <td>
                                  {live(run) ? (
                                    <button
                                      className="icon-button"
                                      aria-label={`Cancel ${runName(run)}`}
                                      title="Cancel run"
                                      onClick={() => void cancel(run.id)}
                                    >
                                      <Square size={15} />
                                    </button>
                                  ) : (
                                    <a
                                      className="icon-button"
                                      aria-label={`Inspect ${runName(run)}`}
                                      title="Inspect run"
                                      href={`#runs/${run.id}`}
                                    >
                                      <ArrowRight size={17} />
                                    </a>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <Empty
                        icon={Search}
                        title="No matching runs on this page"
                        text="Other pages may contain matching runs."
                      />
                    )
                  ) : (
                    <Empty
                      icon={Activity}
                      title={historyError ? "Run history unavailable" : historyOffset ? "No runs on this page" : "No rollout runs yet"}
                      text={historyError ? "Retry loading the current page." : historyOffset ? "Return to a newer page." : "Choose a world and policy to start an episode batch."}
                      action={
                        !historyOffset && !historyError ? <button
                          className="button"
                          disabled={!health}
                          onClick={() => setLaunch("")}
                        >
                          <Play size={16} />
                          Start first rollout
                        </button> : undefined
                      }
                    />
                  )}
                  {runs.length > 15 && (
                    <HistoryPager
                      offset={historyOffset}
                      count={runs.length}
                      hasOlder={hasOlder}
                      loading={historyLoading}
                      change={changeHistoryPage}
                    />
                  )}
                  <div className="section-footer">
                    <span>
                      <GitBranch size={14} /> Seeds and configuration are
                      persisted with every run.
                    </span>
                    <span>Polling every 2 seconds</span>
                  </div>
                </>
              ) : route.view === "worlds" ? (
                <Worlds environments={environments} launch={setLaunch} />
              ) : route.view === "benchmarks" ? (
                <Benchmarks
                  runs={comparisonRuns}
                  pageRuns={runs}
                  selected={selectedRuns}
                  setSelected={selectComparedRuns}
                />
              ) : (
                <Runtime health={health} providers={providers} />
              )}
            </>
          )}
        </main>
        <footer className="app-footer">
          <span>
            World Engine{" "}
            <span className="text-muted">/ research workspace</span>
          </span>
          <span>
            <GitBranch size={13} />
            Reproducible by seed
          </span>
        </footer>
      </div>
      {launch !== null && (
        <LaunchDialog
          environments={environments}
          providers={providers}
          paidCallsEnabled={health?.paid_calls_enabled ?? false}
          initialEnvironment={launch}
          close={() => setLaunch(null)}
          created={(run) => {
            setLaunch(null);
            setNotice("Rollout created.");
            if (historyOffset) changeHistoryPage(0);
            else void refresh();
            go("runs", run.id);
          }}
        />
      )}
    </div>
  );
}

function HistoryPager({ offset, count, hasOlder, loading, change }: {
  offset: number;
  count: number;
  hasOlder: boolean;
  loading: boolean;
  change: (offset: number) => void;
}) {
  return (
    <nav className="history-pager" aria-label="Run history pages">
      <span role="status">
        Page {offset / HISTORY_PAGE_SIZE + 1}
        <span className="text-muted">
          {" / "}{loading ? "Loading" : count ? `Runs ${offset + 1}-${offset + count}` : "No loaded runs"}
        </span>
      </span>
      <div>
        <button className="icon-button" title="Newest runs" aria-label="Newest runs"
          disabled={loading || offset === 0} onClick={() => change(0)}>
          <ChevronsLeft size={17} />
        </button>
        <button className="icon-button" title="Newer runs" aria-label="Newer runs"
          disabled={loading || offset === 0} onClick={() => change(offset - HISTORY_PAGE_SIZE)}>
          <ArrowLeft size={17} />
        </button>
        <button className="icon-button" title="Older runs" aria-label="Older runs"
          disabled={loading || !hasOlder || offset + HISTORY_PAGE_SIZE > HISTORY_MAX_OFFSET}
          onClick={() => change(offset + HISTORY_PAGE_SIZE)}>
          <ArrowRight size={17} />
        </button>
      </div>
    </nav>
  );
}

function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <span />
      {value.replaceAll("_", " ")}
    </span>
  );
}
function Empty({
  icon: Icon,
  title,
  text,
  action,
}: {
  icon: typeof Activity;
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Icon size={28} strokeWidth={1.5} />
      <h2>{title}</h2>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

function Worlds({
  environments,
  launch,
}: {
  environments: Environment[];
  launch: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const world =
    environments.find((item) => item.id === selected) ?? environments[0];
  if (!world)
    return (
      <Empty
        icon={Box}
        title="No environments available"
        text="Connect the local runtime to load the world registry."
      />
    );
  return (
    <div className="world-layout">
      <div className="world-list">
        {environments.map((item, index) => (
          <button
            key={item.id}
            className={`world-item ${world.id === item.id ? "selected" : ""}`}
            onClick={() => setSelected(item.id)}
          >
            <span className="world-number">0{index + 1}</span>
            <div>
              <strong>{item.name}</strong>
              <code>{item.id}</code>
              <div className="tags">
                {item.tags.slice(0, 3).map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            </div>
            <ChevronRight size={18} />
          </button>
        ))}
      </div>
      <section className="world-detail">
        <div className="section-heading">
          <div>
            <span className="eyebrow">ENVIRONMENT / v{world.version}</span>
            <h2>{world.name}</h2>
          </div>
          <button className="button" onClick={() => launch(world.id)}>
            <Play size={16} />
            Run world
          </button>
        </div>
        <p className="world-description">{world.description}</p>
        <div className="world-meta">
          <div>
            <small>World ID</small>
            <code>{world.id}</code>
          </div>
          <div>
            <small>Tool contract</small>
            <strong>{world.tools.length} tools</strong>
          </div>
          <div>
            <small>Scenarios</small>
            <strong>{world.scenario_count ?? "Seed generated"}</strong>
          </div>
        </div>
        <h3 className="subheading">Action tools</h3>
        <div className="tool-list">
          {world.tools.map((tool) => (
            <details key={tool.name}>
              <summary>
                <Terminal size={16} />
                <code>{tool.name}</code>
                <span>{tool.description}</span>
                <ChevronRight size={16} />
              </summary>
              <Json value={tool.args_schema} />
            </details>
          ))}
        </div>
        <div className="world-note">
          <GitBranch size={17} />
          <span>
            Scenario seed, split, observations, and state hashes are recorded
            per episode.
          </span>
        </div>
      </section>
    </div>
  );
}

function Benchmarks({
  runs,
  pageRuns,
  selected,
  setSelected,
}: {
  runs: Run[];
  pageRuns: Run[];
  selected: string[];
  setSelected: (ids: string[]) => void;
}) {
  const eligible = runs.filter((run) => run.completed_episodes > 0);
  const compared = eligible.filter((run) => selected.includes(run.id));
  const shown = compared.length ? compared : pageRuns.filter((run) => run.completed_episodes > 0).slice(0, 6);
  return (
    <>
      <div className="section-heading">
        <h2>Success by run</h2>
        <span className="text-muted">
          {compared.length
            ? `${compared.length} selected`
            : "Up to six results from the loaded page"}
        </span>
      </div>
      {shown.length ? (
        <div className="benchmark-chart" aria-label="Run pass rates">
          {shown.map((run) => (
            <div className="benchmark-row" key={run.id}>
              <a href={`#runs/${run.id}`}>
                <strong>{run.label || run.config.environment_id}</strong>
                <small>
                  {run.config.provider_id} / seed {run.config.seed}
                </small>
              </a>
              <div className="bar-track">
                <div style={{ width: percent(run.success_rate) }} />
              </div>
              <strong>{percent(run.success_rate)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          icon={FlaskConical}
          title="No benchmark results"
          text="Completed episodes will appear here for comparison."
        />
      )}
      <div className="section-heading">
        <h2>Run comparison</h2>
        {selected.length > 0 && (
          <button className="button quiet" onClick={() => setSelected([])}>
            <X size={14} />
            Clear selection
          </button>
        )}
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th aria-label="Select" />
              <th>Run</th>
              <th>World</th>
              <th>Policy / model</th>
              <th>Seed</th>
              <th>Episodes</th>
              <th>Pass rate</th>
              <th>Mean reward</th>
              <th>Steps / sec</th>
            </tr>
          </thead>
          <tbody>
            {eligible.map((run) => (
              <tr key={run.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Compare ${runName(run)}`}
                    checked={selected.includes(run.id)}
                    onChange={(event) =>
                      setSelected(
                        event.target.checked
                          ? [...selected, run.id]
                          : selected.filter((id) => id !== run.id),
                      )
                    }
                  />
                </td>
                <td>
                  <a className="run-link" href={`#runs/${run.id}`}>
                    {run.label || run.id.slice(0, 12)}
                  </a>
                  <Status value={run.status} />
                </td>
                <td>{run.config.environment_id}</td>
                <td>
                  {run.config.provider_id}
                  <small>{run.config.model || "Built-in policy"}</small>
                </td>
                <td className="numeric">{run.config.seed}</td>
                <td className="numeric">{run.completed_episodes}</td>
                <td className="good-text">{percent(run.success_rate)}</td>
                <td className="numeric">{number(run.mean_reward)}</td>
                <td className="numeric">{number(run.steps_per_second)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-footnote">
        Metrics cover completed episodes. Match world, seed, step bounds, and
        split before attributing a difference to the policy.
      </p>
    </>
  );
}

function Runtime({
  health,
  providers,
}: {
  health: Health | null;
  providers: Provider[];
}) {
  return (
    <>
      <div className="runtime-summary">
        <Server size={26} strokeWidth={1.6} />
        <div>
          <h2>Local runtime</h2>
          <code>http://127.0.0.1:8000</code>
        </div>
        <Status value={health ? "connected" : "offline"} />
      </div>
      <dl className="runtime-facts">
        <div>
          <dt>Version</dt>
          <dd>{health?.version ?? "--"}</dd>
        </div>
        <div>
          <dt>Execution</dt>
          <dd>{health?.execution ?? "--"}</dd>
        </div>
        <div>
          <dt>Active runs</dt>
          <dd>{health?.active_runs ?? "--"}</dd>
        </div>
        <div>
          <dt>Model call policy</dt>
          <dd>
            {health?.paid_calls_enabled
              ? "Explicit per-run opt-in"
              : "Paid calls disabled by server"}
          </dd>
        </div>
      </dl>
      <div className="section-heading">
        <h2>
          Providers <span>{providers.length}</span>
        </h2>
        <span className="text-muted">Configured by the server environment</span>
      </div>
      <div className="provider-list">
        {providers.map((provider) => (
          <div className="provider-row" key={provider.id}>
            <span className={`provider-icon ${provider.kind}`}>
              {provider.kind === "scripted" ? (
                <Terminal size={20} />
              ) : (
                <Server size={20} />
              )}
            </span>
            <div>
              <h3>{provider.name}</h3>
              <code>{provider.id}</code>
            </div>
            <div>
              <small>Execution</small>
              <span>{provider.kind}</span>
            </div>
            <div>
              <small>Models</small>
              <span>{provider.models.join(", ") || "Policy default"}</span>
            </div>
            <div>
              <Status value={provider.configured ? "ready" : "unconfigured"} />
              {provider.requires_opt_in && (
                <small>
                  {health?.paid_calls_enabled
                    ? "Per-run opt-in required"
                    : "Server paid gate closed"}
                </small>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="world-note">
        <Settings2 size={17} />
        <span>
          Credentials stay in server environment variables. Runtime readiness is
          read from the API.
        </span>
      </div>
    </>
  );
}

function LaunchDialog({
  environments,
  providers,
  paidCallsEnabled,
  initialEnvironment,
  close,
  created,
}: {
  environments: Environment[];
  providers: Provider[];
  paidCallsEnabled: boolean;
  initialEnvironment: string;
  close: () => void;
  created: (run: Run) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const enabledProviders = providers.filter(
    (provider) =>
      provider.configured && (!provider.requires_opt_in || paidCallsEnabled),
  );
  const [config, setConfig] = useState<RunConfig>({
    environment_id: initialEnvironment || environments[0]?.id || "",
    provider_id: enabledProviders[0]?.id || "",
    episodes: 10,
    seed: 42,
    max_steps: 20,
    concurrency: 4,
    model: defaultModel(enabledProviders[0]),
    allow_paid: false,
    evaluation_only: false,
    timeout_seconds: 60,
    label: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    element?.querySelector("input")?.focus();
    return () => element?.close();
  }, []);
  const provider = providers.find((item) => item.id === config.provider_id);
  const environment = environments.find(
    (item) => item.id === config.environment_id,
  );
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      created(await api.create(config));
    } catch (err) {
      setError(message(err));
      setSubmitting(false);
    }
  };
  return (
    <dialog
      ref={dialog}
      onCancel={close}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
      className="launch-dialog"
      aria-labelledby="launch-title"
    >
      <form onSubmit={(event) => void submit(event)}>
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">EXECUTION CONFIGURATION</span>
            <h2 id="launch-title">New rollout</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label="Close new rollout"
            title="Close"
            onClick={close}
          >
            <X size={20} />
          </button>
        </div>
        <div className="dialog-body">
          {error && (
            <div className="inline-error" role="alert">
              <CircleAlert size={17} />
              {error}
            </div>
          )}
          <label>
            Run label
            <input
              autoFocus
              placeholder="Optional label"
              maxLength={120}
              value={config.label}
              onChange={(event) =>
                setConfig({ ...config, label: event.target.value })
              }
            />
          </label>
          <label>
            Environment
            <select
              aria-label="Environment"
              required
              value={config.environment_id}
              onChange={(event) =>
                setConfig({ ...config, environment_id: event.target.value })
              }
            >
              {environments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p className="field-note">{environment?.description}</p>
          <div className="form-grid">
            <label>
              Provider
              <select
                aria-label="Provider"
                required
                value={config.provider_id}
                onChange={(event) => {
                  const next = providers.find(
                    (item) => item.id === event.target.value,
                  );
                  setConfig({
                    ...config,
                    provider_id: event.target.value,
                    model: defaultModel(next),
                    allow_paid: false,
                  });
                }}
              >
                {providers.map((item) => (
                  <option
                    key={item.id}
                    value={item.id}
                    disabled={
                      !item.configured ||
                      (item.requires_opt_in && !paidCallsEnabled)
                    }
                  >
                    {item.name}
                    {!item.configured
                      ? " (not configured)"
                      : item.requires_opt_in && !paidCallsEnabled
                        ? " (server gate closed)"
                        : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <select
                aria-label="Model"
                value={config.model ?? ""}
                onChange={(event) =>
                  setConfig({ ...config, model: event.target.value || null })
                }
                disabled={!provider?.models.length}
              >
                <option value="">Policy default</option>
                {provider?.models.map((model) => (
                  <option key={model}>{model}</option>
                ))}
              </select>
            </label>
          </div>
          {provider?.requires_opt_in && (
            <label className="paid-consent">
              <input
                type="checkbox"
                required
                checked={config.allow_paid}
                onChange={(event) =>
                  setConfig({ ...config, allow_paid: event.target.checked })
                }
              />
              <span>
                Allow paid model calls for this run. Provider usage charges
                apply.
              </span>
            </label>
          )}
          <div className="form-divider">Episode bounds</div>
          <div className="form-grid">
            {(
              [
                { key: "episodes", label: "Episodes", min: 1, max: 100 },
                {
                  key: "seed",
                  label: "Starting seed",
                  min: 0,
                  max: 2147483647,
                },
                {
                  key: "max_steps",
                  label: "Max steps / episode",
                  min: 1,
                  max: 100,
                },
                { key: "concurrency", label: "Concurrency", min: 1, max: 8 },
                {
                  key: "timeout_seconds",
                  label: "Timeout / episode (s)",
                  min: 1,
                  max: 300,
                },
              ] satisfies {
                key:
                  | "episodes"
                  | "seed"
                  | "max_steps"
                  | "concurrency"
                  | "timeout_seconds";
                label: string;
                min: number;
                max: number;
              }[]
            ).map((field) => (
              <label key={field.key}>
                {field.label}
                <input
                  type="number"
                  required
                  min={field.min}
                  max={field.max}
                  step={1}
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
          <div className="execution-note">
            <GitBranch size={17} />
            <span>
              Each episode records its seed, scenario, split, and final state
              hash.
            </span>
          </div>
          <label className="evaluation-consent">
            <input
              type="checkbox"
              checked={config.evaluation_only}
              onChange={(event) =>
                setConfig({ ...config, evaluation_only: event.target.checked })
              }
            />
            <span>Evaluation-only batch (excluded from training exports)</span>
          </label>
        </div>
        <div className="dialog-footer">
          <span>
            <span className="connection-dot online" />
            Local runtime
          </span>
          <button className="button quiet" type="button" onClick={close}>
            Cancel
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={submitting || !enabledProviders.length}
          >
            {submitting ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Play size={16} />
            )}
            {submitting ? "Creating..." : "Start rollout"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function RunInspector({
  id,
  environments,
  notify,
  cancel,
}: {
  id: string;
  environments: Environment[];
  notify: (value: string) => void;
  cancel: (id: string) => Promise<void>;
}) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [tab, setTab] = useState<"trace" | "provenance">("trace");
  const [format, setFormat] = useState<ExportFormat>("traces");
  const [quality, setQuality] = useState("all");
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    let active = true;
    setRun(null);
    setError("");
    setEpisodeId(null);
    setStepIndex(0);
    const load = async () => {
      try {
        const data = await api.run(id);
        if (active) {
          setRun(data);
          setError("");
        }
      } catch (err) {
        if (active) setError(message(err));
      }
    };
    void load();
    const interval = setInterval(() => void load(), 1500);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [id]);
  const episode =
    run?.episodes.find((item) => item.id === episodeId) ?? run?.episodes[0];
  const step = episode?.trace[stepIndex];
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify("Copied to clipboard.");
    } catch {
      notify("Clipboard permission unavailable.");
    }
  };
  const download = async () => {
    setExporting(true);
    try {
      const result = await api.export(id, format, quality);
      notify(
        result.empty
          ? "Export has no eligible records. Check matching alternatives, split, and provenance."
          : `${result.records} records exported / ${result.skipped} episodes skipped.`,
      );
    } catch (err) {
      notify(message(err));
    } finally {
      setExporting(false);
    }
  };
  if (error && !run)
    return (
      <>
        <a className="back-link" href="#runs">
          <ArrowLeft size={16} />
          Run history
        </a>
        <Empty
          icon={CircleAlert}
          title="Run could not be loaded"
          text={error}
        />
      </>
    );
  if (!run)
    return (
      <Empty
        icon={LoaderCircle}
        title="Loading rollout"
        text="Retrieving episode traces and outcomes."
      />
    );
  const world = environments.find(
    (item) => item.id === run.config.environment_id,
  );
  return (
    <>
      <a className="back-link" href="#runs">
        <ArrowLeft size={16} />
        Run history
      </a>
      <div className="page-heading detail-heading">
        <div>
          <div className="eyebrow">ROLLOUT / {run.config.environment_id}</div>
          <h1>{run.label || world?.name || run.config.environment_id}</h1>
          <div className="detail-subtitle">
            <code>{run.id}</code>
            <button
              className="icon-button small"
              aria-label="Copy run ID"
              title="Copy run ID"
              onClick={() => void copy(run.id)}
            >
              <Copy size={14} />
            </button>
            <Status value={run.status} />
          </div>
        </div>
        {live(run) && (
          <button className="button danger" onClick={() => void cancel(id)}>
            <Square size={15} />
            Cancel run
          </button>
        )}
      </div>
      {run.error && (
        <div className="inline-error" role="alert">
          <CircleAlert size={17} />
          {run.error}
        </div>
      )}
      <div className="metric-strip detail-metrics">
        <Metric
          label="Episodes"
          value={`${run.completed_episodes} / ${run.total_episodes}`}
          note={`${run.passed_episodes} passed / ${run.failed_episodes} failed`}
        />
        <Metric
          label="Pass rate"
          value={percent(run.success_rate)}
          note="Hidden grader outcome"
        />
        <Metric
          label="Mean reward"
          value={number(run.mean_reward)}
          note="Across completed episodes"
        />
        <Metric
          label="Step throughput"
          value={`${number(run.steps_per_second)} steps/s`}
          note={`${duration(run.elapsed_seconds)} elapsed`}
        />
      </div>
      <div className="run-config-bar">
        <span>
          <Box size={15} />
          {world?.name || run.config.environment_id}
        </span>
        <span>
          <Terminal size={15} />
          {run.config.provider_id}
          {run.config.model ? ` / ${run.config.model}` : ""}
        </span>
        <span>
          <GitBranch size={15} />
          Seed {run.config.seed}
        </span>
        <span>
          <Settings2 size={15} />
          {run.config.max_steps} steps / {run.config.concurrency} workers
        </span>
      </div>
      <div className="detail-toolbar">
        <div className="tabs" role="tablist" aria-label="Run views">
          <button
            role="tab"
            aria-selected={tab === "trace"}
            className={tab === "trace" ? "selected" : ""}
            onClick={() => setTab("trace")}
          >
            <Activity size={16} />
            Episode traces
          </button>
          <button
            role="tab"
            aria-selected={tab === "provenance"}
            className={tab === "provenance" ? "selected" : ""}
            onClick={() => setTab("provenance")}
          >
            <GitBranch size={16} />
            Provenance
          </button>
        </div>
        <div className="export-controls">
          <select
            aria-label="Export format"
            value={format}
            onChange={(event) => {
              const selected = event.target.value;
              if (
                selected === "sft" ||
                selected === "dpo" ||
                selected === "grpo" ||
                selected === "atif" ||
                selected === "traces"
              )
                setFormat(selected);
            }}
          >
            <option value="traces">Raw traces</option>
            <option value="atif">Harbor ATIF</option>
            <option value="sft">SFT</option>
            <option value="dpo">DPO pairs</option>
            <option value="grpo">Grouped RL</option>
          </select>
          <select
            aria-label="Export quality"
            value={quality}
            onChange={(event) => setQuality(event.target.value)}
          >
            <option value="all">All episodes</option>
            <option value="passed">Passed only</option>
          </select>
          <button
            className="button"
            disabled={exporting || !run.episodes.length}
            onClick={() => void download()}
          >
            <ArrowDownToLine size={16} />
            Export
          </button>
        </div>
      </div>
      {tab === "provenance" ? (
        <Provenance run={run} world={world} copy={copy} />
      ) : run.episodes.length ? (
        <div className="inspector-layout">
          <aside className="episode-sidebar">
            <div className="episode-list-heading">
              EPISODES <span>{run.episodes.length}</span>
            </div>
            {run.episodes.map((item) => (
              <button
                key={item.id}
                className={`episode-item ${episode?.id === item.id ? "selected" : ""}`}
                onClick={() => {
                  setEpisodeId(item.id);
                  setStepIndex(0);
                }}
              >
                <span>
                  {item.passed ? (
                    <CheckCircle2 size={17} />
                  ) : (
                    <CircleAlert size={17} />
                  )}
                </span>
                <div>
                  <strong>Episode {item.index + 1}</strong>
                  <small>
                    {item.steps} steps / {item.split}
                  </small>
                </div>
                <span className="episode-reward">{number(item.reward)}</span>
              </button>
            ))}
          </aside>
          {episode && (
            <div className="episode-inspector">
              <div className="episode-heading">
                <h2>
                  Episode {episode.index + 1}
                  <Status
                    value={
                      episode.passed
                        ? "passed"
                        : episode.termination === "finished"
                          ? "grader_failed"
                          : episode.termination
                    }
                  />
                </h2>
                <div>
                  <code>seed {episode.seed}</code>
                  <span>{duration(episode.elapsed_seconds)}</span>
                </div>
              </div>
              <div className="episode-strip">
                <span>
                  Scenario{" "}
                  <code title={episode.scenario_id}>
                    {episode.scenario_id.slice(0, 12)}
                  </code>
                </span>
                <span>
                  Split <strong>{episode.split}</strong>
                </span>
                <span>
                  Reward <strong>{number(episode.reward)}</strong>
                </span>
                <span>
                  Termination{" "}
                  <strong>{episode.termination.replaceAll("_", " ")}</strong>
                </span>
                <span>
                  Invalid actions <strong>{episode.invalid_actions}</strong>
                </span>
              </div>
              <EpisodeChart episode={episode} />
              <div className="trace-layout">
                <div className="timeline">
                  <h3>Action timeline</h3>
                  {episode.trace.map((entry, index) => (
                    <button
                      key={entry.index}
                      className={`trace-item ${stepIndex === index ? "selected" : ""}`}
                      onClick={() => setStepIndex(index)}
                    >
                      <span className="step-number">{index + 1}</span>
                      <div>
                        <code>{entry.action.tool}</code>
                        <small>
                          <span
                            className={
                              entry.result.ok ? "good-text" : "bad-text"
                            }
                          >
                            {entry.result.ok ? "Accepted" : "Rejected"}
                          </span>{" "}
                          / {number(entry.elapsed_ms)} ms
                        </small>
                      </div>
                      <ChevronRight size={14} />
                    </button>
                  ))}
                  {!episode.trace.length && (
                    <p className="text-muted">No actions recorded.</p>
                  )}
                </div>
                <div className="step-detail">
                  {step ? (
                    <>
                      <div className="step-heading">
                        <h3>
                          Step {stepIndex + 1} <code>{step.action.tool}</code>
                        </h3>
                        <button
                          className="icon-button"
                          aria-label="Copy action JSON"
                          title="Copy action JSON"
                          onClick={() =>
                            void copy(JSON.stringify(step.action, null, 2))
                          }
                        >
                          <Copy size={15} />
                        </button>
                      </div>
                      <h4>Action arguments</h4>
                      <Json value={step.action.args} />
                      <h4>Tool result</h4>
                      <Json value={step.result} />
                      <details>
                        <summary>Provider usage</summary>
                        <Json value={step.usage} />
                      </details>
                      <details open>
                        <summary>Observation after action</summary>
                        <Json value={step.observation} />
                      </details>
                      <div className="hash-line">
                        State hash{" "}
                        <code title={step.state_hash}>
                          {step.state_hash.slice(0, 20)}
                        </code>
                      </div>
                    </>
                  ) : (
                    <Empty
                      icon={Terminal}
                      title="No trace steps"
                      text="This episode ended before an action was recorded."
                    />
                  )}
                </div>
              </div>
              <Grader episode={episode} />
              <div className="observation-grid">
                <details>
                  <summary>Initial observation</summary>
                  <Json value={episode.initial_observation} />
                </details>
                <details>
                  <summary>Final observation</summary>
                  <Json value={episode.final_observation} />
                </details>
              </div>
            </div>
          )}
        </div>
      ) : (
        <Empty
          icon={live(run) ? LoaderCircle : Activity}
          title={live(run) ? "Episodes are running" : "No completed episodes"}
          text={
            live(run)
              ? "Episode traces appear as the runtime records outcomes."
              : "This run has no episode traces to inspect."
          }
        />
      )}
    </>
  );
}

function EpisodeChart({ episode }: { episode: Episode }) {
  const maximum = Math.max(1, ...episode.trace.map((step) => step.elapsed_ms));
  return (
    <div className="latency-chart">
      <div>
        <h3>Action latency</h3>
        <span>{episode.trace.length} recorded actions</span>
      </div>
      <div className="latency-bars" aria-label="Action latency chart">
        {episode.trace.map((step, index) => (
          <div
            key={step.index}
            title={`${step.action.tool}: ${number(step.elapsed_ms)} ms`}
          >
            <span
              style={{
                height: `${Math.max(3, (step.elapsed_ms / maximum) * 100)}%`,
              }}
              className={step.result.ok ? "" : "rejected"}
            />
            <small>{index + 1}</small>
          </div>
        ))}
      </div>
      <span className="latency-max">{number(maximum)} ms max</span>
    </div>
  );
}
function Grader({ episode }: { episode: Episode }) {
  return (
    <section className="grader-section">
      <div className="section-heading">
        <h3>Hidden grader</h3>
        <span className="text-muted">
          {episode.grader.checks.filter((check) => check.passed).length} /{" "}
          {episode.grader.checks.length} checks passed
        </span>
      </div>
      {episode.error && <div className="inline-error">{episode.error}</div>}
      <div className="grader-checks">
        {episode.grader.checks.map((check) => (
          <div key={check.name} className="grader-check">
            {check.passed ? (
              <CheckCircle2 size={17} className="good-text" />
            ) : (
              <CircleAlert size={17} className="bad-text" />
            )}
            <div>
              <strong>{check.name}</strong>
              <p>{check.detail}</p>
            </div>
            <span>{check.passed ? "Pass" : "Fail"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
function Provenance({
  run,
  world,
  copy,
}: {
  run: RunDetail;
  world?: Environment;
  copy: (value: string) => Promise<void>;
}) {
  return (
    <section className="provenance">
      <div className="provenance-grid">
        <div>
          <h3>Run configuration</h3>
          <Json value={run.config} />
        </div>
        <div>
          <h3>Registry & execution</h3>
          <dl className="provenance-facts">
            <div>
              <dt>Environment</dt>
              <dd>{run.config.environment_id}</dd>
            </div>
            <div>
              <dt>Recorded environment version</dt>
              <dd>
                {[
                  ...new Set(
                    run.episodes.map(
                      (episode) => episode.provenance.environment_version,
                    ),
                  ),
                ].join(", ") || "--"}
              </dd>
            </div>
            <div>
              <dt>Recorded grader version</dt>
              <dd>
                {[
                  ...new Set(
                    run.episodes.map(
                      (episode) => episode.provenance.grader_version,
                    ),
                  ),
                ].join(", ") || "--"}
              </dd>
            </div>
            <div>
              <dt>Current registry version</dt>
              <dd>{world?.version ?? "--"}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{new Date(run.created_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{new Date(run.updated_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Recorded splits</dt>
              <dd>
                {["train", "validation", "test"]
                  .map(
                    (split) =>
                      `${split}: ${run.episodes.filter((episode) => episode.split === split).length}`,
                  )
                  .join(" / ")}
              </dd>
            </div>
          </dl>
        </div>
      </div>
      <div className="section-heading">
        <h3>Episode provenance</h3>
        <button
          className="button quiet"
          onClick={() =>
            void copy(
              JSON.stringify(
                run.episodes.map(
                  ({
                    id,
                    seed,
                    split,
                    scenario_id,
                    lineage_id,
                    final_state_hash,
                    provenance,
                    termination,
                    usage,
                  }) => ({
                    id,
                    seed,
                    split,
                    scenario_id,
                    lineage_id,
                    provenance,
                    termination,
                    usage,
                    final_state_hash,
                  }),
                ),
                null,
                2,
              ),
            )
          }
        >
          <Copy size={15} />
          Copy metadata
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Episode</th>
              <th>Seed</th>
              <th>Scenario</th>
              <th>Split</th>
              <th>Termination</th>
              <th>Final state hash</th>
            </tr>
          </thead>
          <tbody>
            {run.episodes.map((episode) => (
              <tr key={episode.id}>
                <td>{episode.index + 1}</td>
                <td className="numeric">{episode.seed}</td>
                <td>
                  <code>{episode.scenario_id}</code>
                </td>
                <td>{episode.split}</td>
                <td>{episode.termination.replaceAll("_", " ")}</td>
                <td>
                  <code title={episode.final_state_hash}>
                    {episode.final_state_hash}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="section-heading">
        <h3>Frozen episode metadata</h3>
        <span className="text-muted">Recorded at execution time</span>
      </div>
      <div className="frozen-provenance">
        {run.episodes.map((episode) => (
          <details key={episode.id}>
            <summary>
              <span>
                Episode {episode.index + 1} / seed {episode.seed}
              </span>
              <span>
                {episode.provenance.environment_version} /{" "}
                {episode.provenance.policy_identity}
              </span>
            </summary>
            <Json
              value={{
                provenance: episode.provenance,
                lineage_id:
                  episode.lineage_id ?? episode.provenance.lineage_id ?? null,
                termination: episode.termination,
                invalid_actions: episode.invalid_actions,
                usage: episode.usage,
              }}
            />
          </details>
        ))}
      </div>
    </section>
  );
}
