import { useEffect, useState, useRef, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Boxes,
  Check,
  Cpu,
  FlaskConical,
  LayoutDashboard,
  Menu,
  MonitorPlay,
  Moon,
  Plus,
  RefreshCw,
  Settings,
  Sun,
  Terminal,
  Zap,
} from "lucide-react";
import { api, ApiError } from "./api";
import { ExperimentForm } from "./ExperimentForm";
import { Analytics, MetricChart } from "./Analytics";
import { Spectator } from "./Spectator";
import { SceneView } from "./SceneView";
import type { Config, Experiment, Game } from "./types";
const pages = [
  ["Dashboard", LayoutDashboard],
  ["Experiments", FlaskConical],
  ["Spectator", MonitorPlay],
  ["Analytics", BarChart3],
  ["Games & Plugins", Boxes],
  ["Workers", Cpu],
  ["Logs", Terminal],
  ["Settings", Settings],
] as const;
const active = ["STARTING", "RUNNING", "PAUSED", "STOPPING"];
const fmt = (n: unknown) =>
  typeof n === "number"
    ? new Intl.NumberFormat(undefined, {
        maximumFractionDigits: 2,
        notation: Math.abs(n) > 99999 ? "compact" : "standard",
      }).format(n)
    : String(n ?? "—");
function Status({ run }: { run: Experiment }) {
  return (
    <span className={`badge status-${run.status.toLowerCase()}`}>
      {run.archived ? "Archived" : run.status.toLowerCase()}
    </span>
  );
}
function GameCard({ game }: { game: Game }) {
  const scene = useQuery({
    queryKey: ["scene", game.id],
    queryFn: () => api.scene(game.id),
  });
  return (
    <article className="panel game-card">
      <SceneView
        scene={scene.data?.scene}
        text={scene.data?.text}
        game={game.id}
      />
      <div className="section-title">
        <h2>{game.name}</h2>
        <span className="badge">v{game.version}</span>
      </div>
      <p>
        {game.observation_size} observations · {game.action_size} actions
      </p>
      <p className="muted">Score: {game.score_name}</p>
      {scene.error && <p role="alert">{scene.error.message}</p>}
    </article>
  );
}
export default function App() {
  const client = useQueryClient();
  const returnFocus = useRef<HTMLElement | null>(null);
  const [page, setPage] = useState("Dashboard"),
    [selected, setSelected] = useState(""),
    [creating, setCreating] = useState(false),
    [sidebar, setSidebar] = useState(false),
    [notice, setNotice] = useState(""),
    [token, setToken] = useState(""),
    [theme, setTheme] = useState(() => {
      try {
        return localStorage.getItem("evoforge-theme") || "dark";
      } catch {
        return "dark";
      }
    });
  const [dialog, setDialog] = useState<{
      action: string;
      run: Experiment;
    } | null>(null),
    [destination, setDestination] = useState(""),
    [extension, setExtension] = useState(100);
  useEffect(() => {
    if (!dialog) return;
    const modal = document.querySelector<HTMLElement>('[role="dialog"]');
    const background = document.querySelectorAll<HTMLElement>(
      ".main-shell, .sidebar",
    );
    background.forEach((element) => (element.inert = true));
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !modal) return;
      const items = [
        ...modal.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input, select, textarea, [tabindex="0"]',
        ),
      ];
      const first = items[0],
        last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    modal?.addEventListener("keydown", trap);
    return () => {
      background.forEach((element) => (element.inert = false));
      modal?.removeEventListener("keydown", trap);
      returnFocus.current?.focus();
    };
  }, [dialog]);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: false,
    refetchInterval: 10000,
  });
  const unauthorized =
    health.error instanceof ApiError && health.error.status === 401;
  const enabled = health.isSuccess;
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    enabled,
    refetchInterval: 2000,
  });
  const games = useQuery({
    queryKey: ["games"],
    queryFn: api.games,
    enabled,
    staleTime: 60000,
  });
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    enabled,
    refetchInterval: 3000,
  });
  const all = runs.data || [];
  const current =
    all.find((r) => r.id === selected) ||
    all.find((r) => !r.archived) ||
    all[0];
  const id = current?.id || "";
  const metrics = useQuery({
    queryKey: ["metrics", id],
    queryFn: () => api.metrics(id),
    enabled: enabled && !!id,
    refetchInterval: 3000,
  });
  const logs = useQuery({
    queryKey: ["logs", id],
    queryFn: () => api.logs(id),
    enabled: enabled && page === "Logs" && !!id,
    refetchInterval: 2000,
  });
  const checkpoints = useQuery({
    queryKey: ["checkpoints", id],
    queryFn: () => api.checkpoints(id),
    enabled: enabled && !!id && page === "Experiments",
    refetchInterval: 5000,
  });
  const workers = useQuery({
    queryKey: ["workers"],
    queryFn: api.workers,
    enabled: enabled && page === "Workers",
    refetchInterval: 2000,
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("evoforge-theme", theme);
    } catch {
      /* Theme still works in memory when storage is unavailable. */
    }
  }, [theme]);
  async function refresh() {
    await client.invalidateQueries();
  }
  const login = useMutation({
    mutationFn: () => api.login(token),
    onSuccess: () => {
      setToken("");
      void refresh();
    },
  });
  const create = useMutation({
    mutationFn: ({ name, config }: { name: string; config: Config }) =>
      api.create(name, config),
    onSuccess: (run) => {
      setSelected(run.id);
      setCreating(false);
      setPage("Experiments");
      setNotice(`Created ${run.id}`);
      void refresh();
    },
  });
  const mutate = useMutation({
    mutationFn: async () => {
      if (!dialog) throw Error("No action selected");
      return dialog.action === "extend"
        ? api.update(dialog.run.id, {
            ...dialog.run.config,
            generations: dialog.run.config.generations + extension,
          })
        : api.action(dialog.run.id, dialog.action, destination);
    },
    onSuccess: (run) => {
      setSelected(run.id);
      setNotice(`${dialog?.action} completed for ${run.id}`);
      setDialog(null);
      void refresh();
    },
  });
  function action(run: Experiment, kind: string) {
    returnFocus.current = document.activeElement as HTMLElement;
    setDestination("");
    setExtension(100);
    mutate.reset();
    setDialog({ run, action: kind });
  }
  function controls(run: Experiment) {
    return (
      <div className="toolbar run-controls">
        {!active.includes(run.status) && !run.archived && (
          <button className="primary" onClick={() => action(run, "start")}>
            Start
          </button>
        )}
        {run.status === "RUNNING" && (
          <button onClick={() => action(run, "pause")}>Pause</button>
        )}
        {run.status === "PAUSED" && (
          <button onClick={() => action(run, "resume")}>Resume</button>
        )}
        {["RUNNING", "PAUSED", "STARTING"].includes(run.status) && (
          <button className="danger" onClick={() => action(run, "stop")}>
            Stop
          </button>
        )}
        <button onClick={() => action(run, "duplicate")}>Duplicate</button>
        <button
          disabled={active.includes(run.status)}
          onClick={() => action(run, "rename")}
        >
          Rename
        </button>
        <button
          disabled={active.includes(run.status)}
          onClick={() => action(run, run.archived ? "unarchive" : "archive")}
        >
          {run.archived ? "Unarchive" : "Archive"}
        </button>
        <button
          disabled={active.includes(run.status)}
          onClick={() => action(run, "extend")}
        >
          Extend training
        </button>
      </div>
    );
  }
  function navigate(next: string) {
    setPage(next);
    setSidebar(false);
    setCreating(false);
  }
  const latest = metrics.data?.at(-1);
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className={sidebar ? "sidebar open" : "sidebar"}>
        <a href="#" className="brand" onClick={() => navigate("Dashboard")}>
          <span className="brand-icon">
            <Zap size={22} />
          </span>
          <span>
            EvoForge<small>EVOLUTION WORKSPACE</small>
          </span>
        </a>
        <span className="nav-label">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {pages.map(([name, Icon]) => (
            <button
              key={name}
              className={page === name ? "nav-item selected" : "nav-item"}
              aria-current={page === name ? "page" : undefined}
              onClick={() => navigate(name)}
            >
              <Icon size={18} />
              {name}
              {name === "Workers" && (
                <span className="nav-count">
                  {dashboard.data?.active_workers ?? "—"}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className={`connection ${health.isSuccess ? "online" : ""}`}>
            <i />
            {health.isSuccess
              ? "Backend connected"
              : unauthorized
                ? "Sign-in required"
                : "Backend unavailable"}
          </div>
          <small>WEB 0.1 · LOCAL CONTROL</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="toolbar">
            <button
              className="mobile-menu"
              aria-label="Toggle navigation"
              onClick={() => setSidebar(!sidebar)}
            >
              <Menu size={20} />
            </button>
            <span className="breadcrumb">
              Workspace <span>/</span> <b>{page}</b>
            </span>
          </div>
          <div className="toolbar">
            <label className="run-picker">
              <span className="sr-only">Open experiment</span>
              <select
                aria-label="Open experiment"
                value={id}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="" disabled>
                  Select experiment
                </option>
                {all.map((r) => (
                  <option value={r.id} key={r.id}>
                    {r.id}
                    {r.archived ? " (archived)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button
              aria-label="Toggle theme"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <span className="eyebrow">EVOLVE. OBSERVE. UNDERSTAND.</span>
              <h1>{page === "Dashboard" ? "Your evolution lab." : page}</h1>
              <p className="muted">
                {page === "Dashboard"
                  ? "Every generation, a new possibility. Track your experiments as they learn."
                  : "Explore real experiments, measured results, and the agents behind them."}
              </p>
            </div>
            <button
              className="primary"
              onClick={() => {
                setPage("Experiments");
                setCreating(true);
              }}
              disabled={!enabled}
            >
              <Plus size={16} /> New experiment
            </button>
          </div>
          {notice && (
            <div role="status" className="notice">
              <Check size={16} />
              {notice}
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                ×
              </button>
            </div>
          )}
          {unauthorized ? (
            <section className="panel login">
              <h2>Connect to your lab</h2>
              <p>
                Enter the operator API token to establish an eight-hour browser
                session.
              </p>
              <form
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  login.mutate();
                }}
              >
                <label>
                  API token
                  <input
                    type="password"
                    autoComplete="off"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    required
                  />
                </label>
                <button className="primary" disabled={login.isPending}>
                  Connect
                </button>
              </form>
              {login.error && <p role="alert">{login.error.message}</p>}
            </section>
          ) : health.isPending ? (
            <p className="empty panel">Connecting to the backend…</p>
          ) : health.error ? (
            <section className="panel error" role="alert">
              {health.error.message}
              <button onClick={() => void refresh()}>Retry connection</button>
            </section>
          ) : (
            <>
              {(runs.error || games.error || dashboard.error) && (
                <p role="alert" className="error">
                  {runs.error?.message ||
                    games.error?.message ||
                    dashboard.error?.message}
                  <button onClick={() => void refresh()}>Retry</button>
                </p>
              )}
              {creating && (
                <ExperimentForm
                  games={games.data || []}
                  onSubmit={(name, config) => create.mutate({ name, config })}
                  onCancel={() => setCreating(false)}
                  pending={create.isPending}
                  error={create.error?.message}
                />
              )}
              {page === "Dashboard" && (
                <>
                  <section className="stat-grid">
                    {[
                      [
                        "Active workers",
                        dashboard.data?.active_workers,
                        "Background training",
                      ],
                      ["Experiments", all.length, "Across installed games"],
                      [
                        "Latest champion",
                        latest?.hall_of_fame,
                        current?.id || "No experiment selected",
                      ],
                      [
                        "Environment steps",
                        latest?.environment_steps,
                        "Measured interactions",
                      ],
                    ].map(([label, value, hint]) => (
                      <article className="stat" key={String(label)}>
                        <span>{label}</span>
                        <strong>{String(fmt(value))}</strong>
                        <small>{hint}</small>
                      </article>
                    ))}
                  </section>
                  <div className="dashboard-grid">
                    <div>
                      <MetricChart
                        title="Learning over generations"
                        rows={metrics.data || []}
                        keys={["best_train", "mean_train", "best_validation"]}
                      />
                      <section className="panel">
                        <div className="section-title">
                          <h2>Recent experiments</h2>
                          <button
                            className="text-button"
                            onClick={() => navigate("Experiments")}
                          >
                            View all <ArrowUpRight size={15} />
                          </button>
                        </div>
                        {all.length ? (
                          <div className="run-list">
                            {[...all]
                              .sort((a, b) => b.updated - a.updated)
                              .slice(0, 5)
                              .map((r) => (
                                <button
                                  className="run-row"
                                  key={r.id}
                                  onClick={() => {
                                    setSelected(r.id);
                                    navigate("Experiments");
                                  }}
                                >
                                  <span className="game-symbol">
                                    <FlaskConical size={18} />
                                  </span>
                                  <span>
                                    <b>{r.id}</b>
                                    <small>
                                      {r.config.game} · {r.config.mode}
                                    </small>
                                  </span>
                                  <Status run={r} />
                                  <span className="run-score">
                                    {String(
                                      fmt(
                                        dashboard.data?.latest[r.id]
                                          ?.hall_of_fame,
                                      ),
                                    )}
                                  </span>
                                  <ArrowUpRight size={16} />
                                </button>
                              ))}
                          </div>
                        ) : (
                          <div className="empty">
                            <FlaskConical size={30} />
                            <h3>Your first generation starts here.</h3>
                            <p>
                              Create an experiment to begin collecting real
                              results.
                            </p>
                          </div>
                        )}
                      </section>
                    </div>
                    <div>
                      <section className="panel system-panel">
                        <div className="section-title">
                          <h2>System pulse</h2>
                          <Activity size={18} />
                        </div>
                        <p className="muted">Host resource snapshot</p>
                        <div className="resource">
                          <span>Memory</span>
                          <b>
                            {dashboard.data?.resources.memory_used_bytes
                              ? `${fmt(dashboard.data.resources.memory_used_bytes / 1024 ** 3)} / ${fmt((dashboard.data.resources.memory_total_bytes || 0) / 1024 ** 3)} GiB`
                              : "Unavailable"}
                          </b>
                        </div>
                        <meter
                          min={0}
                          max={
                            dashboard.data?.resources.memory_total_bytes || 1
                          }
                          value={
                            dashboard.data?.resources.memory_used_bytes || 0
                          }
                        />
                        <div className="resource">
                          <span>CPU utilization</span>
                          <b>
                            {dashboard.data?.resources.cpu_percent == null
                              ? "Awaiting sample"
                              : `${fmt(dashboard.data.resources.cpu_percent)}%`}
                          </b>
                        </div>
                        <div className="resource">
                          <span>CPU load (1 minute)</span>
                          <b>
                            {String(
                              fmt(dashboard.data?.resources.load_average?.[0]),
                            )}
                          </b>
                        </div>
                        <p className="muted">
                          {dashboard.data?.resources.cpu_count ?? "—"} logical
                          CPUs · load is not a percentage
                        </p>
                        <div className="resource">
                          <span>GPU detected</span>
                          <b>
                            {dashboard.data?.resources.gpu.available
                              ? "Yes"
                              : "No"}
                          </b>
                        </div>
                        <p className="muted">
                          {dashboard.data?.resources.gpu.note}
                        </p>
                      </section>
                      <section className="panel">
                        <h2>Experiment activity</h2>
                        <div className="activity-list">
                          {dashboard.data?.activity
                            .slice(-6)
                            .reverse()
                            .map((e) => (
                              <div key={e.seq}>
                                <i />
                                <span>
                                  <b>{e.experiment}</b>
                                  <small>
                                    {e.type} ·{" "}
                                    {new Date(
                                      e.timestamp * 1000,
                                    ).toLocaleTimeString()}
                                  </small>
                                </span>
                              </div>
                            ))}
                          {!dashboard.data?.activity.length && (
                            <p className="muted">
                              Activity appears as experiments run.
                            </p>
                          )}
                        </div>
                      </section>
                      {!!dashboard.data?.warnings.length && (
                        <section className="panel">
                          <h2>Warnings & failures</h2>
                          {dashboard.data.warnings.map((w) => (
                            <p className="error" key={w.experiment}>
                              {w.experiment}: {w.error}
                            </p>
                          ))}
                        </section>
                      )}
                    </div>
                  </div>
                </>
              )}
              {page === "Experiments" && !creating && (
                <>
                  <section className="panel">
                    <div className="section-title">
                      <h2>
                        Experiment library{" "}
                        <span className="muted">{all.length}</span>
                      </h2>
                      <button
                        aria-label="Refresh experiments"
                        onClick={() => void refresh()}
                      >
                        <RefreshCw size={16} />
                      </button>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Experiment</th>
                            <th>Environment</th>
                            <th>Algorithm</th>
                            <th>Status</th>
                            <th>Progress</th>
                            <th />
                          </tr>
                        </thead>
                        <tbody>
                          {all.map((r) => (
                            <tr
                              key={r.id}
                              className={id === r.id ? "current-row" : ""}
                            >
                              <td>
                                <b>{r.id}</b>
                              </td>
                              <td>{r.config.game}</td>
                              <td>{r.config.mode}</td>
                              <td>
                                <Status run={r} />
                              </td>
                              <td>
                                {r.worker?.generation ?? 0} /{" "}
                                {r.config.generations}
                              </td>
                              <td>
                                <button
                                  onClick={() => setSelected(r.id)}
                                  aria-label={`Open ${r.id}`}
                                >
                                  Open <ArrowUpRight size={14} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {!all.length && (
                      <p className="empty">
                        No experiments yet. Create one to get started.
                      </p>
                    )}
                  </section>
                  {current && (
                    <section className="panel">
                      <div className="section-title">
                        <div>
                          <span className="eyebrow">OPEN EXPERIMENT</span>
                          <h2>{current.id}</h2>
                        </div>
                        <Status run={current} />
                      </div>
                      {controls(current)}
                      {active.includes(current.status) && (
                        <p className="muted">
                          Stop the worker before renaming, archiving, or
                          extending this experiment.
                        </p>
                      )}
                      <div className="toolbar">
                        <button onClick={() => navigate("Spectator")}>
                          Watch gameplay
                        </button>
                        <button onClick={() => navigate("Analytics")}>
                          Review analytics
                        </button>
                        {(["csv", "json"] as const).map((format) => (
                          <button
                            key={format}
                            onClick={() =>
                              void api
                                .export(id, format)
                                .catch((e) => setNotice(e.message))
                            }
                          >
                            Export {format.toUpperCase()}
                          </button>
                        ))}
                      </div>
                      <details>
                        <summary>Training configuration</summary>
                        <pre>{JSON.stringify(current.config, null, 2)}</pre>
                      </details>
                      <h3>Checkpoints</h3>
                      {checkpoints.data?.length ? (
                        <ul className="file-list">
                          {checkpoints.data.map((c) => (
                            <li key={c.name}>
                              <code>{c.name}</code>
                              <span>
                                {fmt(c.bytes / 1024)} KiB ·{" "}
                                {new Date(c.updated * 1000).toLocaleString()}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">
                          No checkpoints have been committed yet.
                        </p>
                      )}
                      {checkpoints.error && (
                        <p role="alert">{checkpoints.error.message}</p>
                      )}
                    </section>
                  )}
                </>
              )}
              {page === "Spectator" && <Spectator key={id} run={current} />}
              {page === "Analytics" && <Analytics runs={all} selected={id} />}
              {page === "Games & Plugins" && (
                <>
                  <div className="panel">
                    <h2>Installed environments</h2>
                    <p className="muted">
                      Discovered from the backend’s Game SDK. Each visual is
                      rendered from its plugin’s scene and asset manifest.
                    </p>
                  </div>
                  <div className="agent-grid">
                    {games.data?.map((g) => (
                      <GameCard key={g.id} game={g} />
                    ))}
                  </div>
                </>
              )}
              {page === "Workers" && (
                <section className="panel">
                  <h2>Worker processes</h2>
                  {workers.isPending ? (
                    <p>Loading workers…</p>
                  ) : !workers.data?.length ? (
                    <p className="empty">No workers have started yet.</p>
                  ) : (
                    workers.data.map((r) => (
                      <article className="worker-row" key={r.id}>
                        <div className="section-title">
                          <h3>{r.id}</h3>
                          <Status run={r} />
                        </div>
                        <p className="muted">
                          PID {r.worker?.pid} · generation{" "}
                          {r.worker?.generation} · heartbeat{" "}
                          {r.worker
                            ? new Date(
                                r.worker.heartbeat * 1000,
                              ).toLocaleTimeString()
                            : "—"}
                        </p>
                        {r.worker?.request && (
                          <p>Pending request: {r.worker.request}</p>
                        )}
                        {r.worker?.error && (
                          <p className="error">{r.worker.error}</p>
                        )}
                        {controls(r)}
                      </article>
                    ))
                  )}
                  {workers.error && <p role="alert">{workers.error.message}</p>}
                </section>
              )}
              {page === "Logs" && (
                <section className="panel">
                  <div className="section-title">
                    <h2>{id || "Select an experiment"} · worker log</h2>
                    <span className="badge">Refreshes every 2s</span>
                  </div>
                  {logs.data?.truncated && <p>Showing the latest 64 KiB.</p>}
                  <pre className="log-view">
                    {logs.error?.message ||
                      logs.data?.text ||
                      "No worker output yet."}
                  </pre>
                </section>
              )}
              {page === "Settings" && (
                <section className="panel settings-panel">
                  <h2>Workspace preferences</h2>
                  <label>
                    Theme
                    <select
                      aria-label="Theme"
                      value={theme}
                      onChange={(e) => setTheme(e.target.value)}
                    >
                      <option value="dark">Forest dark</option>
                      <option value="light">Paper light</option>
                    </select>
                  </label>
                  <p className="muted">
                    Only your theme preference is saved in browser storage. The
                    renderer respects your system’s reduced-motion preference.
                  </p>
                  <h3>Connection</h3>
                  <p>Same-origin API · {location.origin}/api/v1</p>
                  <p>
                    Browser sessions expire after eight hours. Remote access
                    requires an operator token and a secured connection.
                  </p>
                  <button
                    onClick={() =>
                      void api
                        .logout()
                        .then(() => {
                          client.clear();
                          void refresh();
                        })
                        .catch((e) => setNotice(e.message))
                    }
                  >
                    Sign out
                  </button>
                  <h3>Rendering & storage</h3>
                  <p>
                    Renderer protocol 1 · replay format 1. Retention is
                    configured by the operator using EVOFORGE_REPLAY_BYTES and
                    EVOFORGE_REPLAY_EPISODES.
                  </p>
                </section>
              )}
            </>
          )}
        </main>
        <footer className="footer">
          <span>
            EvoForge <span className="muted">/</span> A place for agents to
            grow.
          </span>
          <span>Measured. Reproducible. Yours.</span>
        </footer>
      </div>
      {dialog && (
        <div
          className="modal-backdrop"
          onKeyDown={(e) => {
            if (e.key === "Escape" && !mutate.isPending) setDialog(null);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="modal panel"
          >
            <h2 id="confirm-title">
              {dialog.action.charAt(0).toUpperCase() + dialog.action.slice(1)}{" "}
              experiment
            </h2>
            <p>
              {dialog.action === "duplicate"
                ? "Create a fresh experiment with the same configuration. The original data remains intact."
                : dialog.action === "archive"
                  ? "Archive this experiment while preserving all its data."
                  : dialog.action === "stop"
                    ? "Stop training cooperatively. Completed generations and saved recordings are preserved."
                    : `Apply ${dialog.action} to ${dialog.run.id}?`}
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                mutate.mutate();
              }}
            >
              {["duplicate", "rename"].includes(dialog.action) && (
                <label>
                  Destination name
                  <input
                    autoFocus
                    required
                    pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,79}"
                    maxLength={80}
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                  />
                </label>
              )}
              {dialog.action === "extend" && (
                <label>
                  Additional generations
                  <input
                    autoFocus
                    type="number"
                    min={1}
                    max={1000000 - dialog.run.config.generations}
                    required
                    value={extension}
                    onChange={(e) => setExtension(Number(e.target.value))}
                  />
                </label>
              )}
              {mutate.error && (
                <p role="alert" className="error">
                  {mutate.error.message}
                </p>
              )}
              <div className="toolbar">
                <button
                  type="button"
                  disabled={mutate.isPending}
                  onClick={() => setDialog(null)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary"
                  autoFocus={
                    !["duplicate", "rename", "extend"].includes(dialog.action)
                  }
                  disabled={mutate.isPending}
                >
                  {mutate.isPending ? "Applying…" : `Confirm ${dialog.action}`}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
