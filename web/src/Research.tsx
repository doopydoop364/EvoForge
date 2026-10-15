import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch,
  BookmarkPlus,
  ArrowRight,
  Download,
  Play,
  Pause,
  Database,
  FlaskConical,
} from "lucide-react";
import { api } from "./api";
import { MetricChart, Analytics } from "./Analytics";
import {
  research,
  type AgentNode,
  type Bookmark,
  type Family,
  type Job,
  type ResearchMeta,
} from "./researchApi";
import type { Experiment } from "./types";

export const researchPages = [
  "Family Trees",
  "Genetic Comparison",
  "Evolution Replay",
  "Compare Runs",
  "Tournament Lab",
  "Research Bookmarks",
  "Storage Manager",
  "Backups",
  "System Resources",
  "Benchmarks",
];
const format = (n: number | null | undefined) =>
  n == null
    ? "Not recorded"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(n);
const bytes = (n: number) => `${(n / 1048576).toFixed(1)} MiB`;
const key = (id: string) => ["research", id];
function useAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["research"] });
      void client.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
function Feedback({ action }: { action: ReturnType<typeof useAction> }) {
  return (
    <>
      {action.isPending && <p role="status">Working…</p>}
      {action.error && (
        <p role="alert" className="error">
          {action.error.message}
        </p>
      )}
      {action.isSuccess && (
        <p role="status" className="research-success">
          Saved successfully.
        </p>
      )}
    </>
  );
}
function Remove({
  label,
  onConfirm,
  disabled = false,
}: {
  label: string;
  onConfirm: () => void;
  disabled?: boolean;
}) {
  const [confirm, setConfirm] = useState(false);
  return confirm ? (
    <span className="toolbar">
      <span>Remove this saved item?</span>
      <button
        className="danger"
        disabled={disabled}
        onClick={() => {
          onConfirm();
          setConfirm(false);
        }}
      >
        Confirm removal
      </button>
      <button onClick={() => setConfirm(false)}>Keep</button>
    </span>
  ) : (
    <button disabled={disabled} onClick={() => setConfirm(true)}>
      {label}
    </button>
  );
}
function Missing({ id, meta }: { id: string; meta?: ResearchMeta }) {
  const action = useAction();
  if (meta?.indexed_generation !== undefined) return null;
  return (
    <section className="panel research-empty">
      <GitBranch size={28} />
      <h2>Build this experiment’s research index</h2>
      <p>
        New training records its history automatically. For an older, stopped
        experiment, import its saved checkpoint to see the ancestry and
        parameters it actually contains.
      </p>
      <button
        disabled={action.isPending}
        onClick={() => action.mutate(() => research.index(id))}
      >
        Index saved checkpoint
      </button>
      <Feedback action={action} />
    </section>
  );
}
export function Notebook({ id }: { id: string }) {
  const meta = useQuery({
    queryKey: [...key(id), "meta"],
    queryFn: () => research.meta(id),
  });
  if (meta.error)
    return <p role="alert">Research notes: {meta.error.message}</p>;
  return meta.data ? (
    <NotebookForm key={id} id={id} initial={meta.data} />
  ) : (
    <p>Loading research notes…</p>
  );
}
function NotebookForm({ id, initial }: { id: string; initial: ResearchMeta }) {
  const [notes, setNotes] = useState(initial.notes),
    [tags, setTags] = useState(initial.tags.join(", "));
  const action = useAction();
  return (
    <section className="panel">
      <div className="section-title">
        <h2>Research notebook</h2>
        <span className="badge">{id}</span>
      </div>
      <p className="muted">
        Record a hypothesis, observations, and the next experiment to try.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate(() =>
            research.annotate(
              id,
              notes,
              tags
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            ),
          );
        }}
      >
        <label>
          Notes
          <textarea
            aria-label="Notes"
            rows={5}
            maxLength={20000}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        <label>
          Tags, separated by commas
          <input
            maxLength={820}
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="baseline, promising, needs review"
          />
        </label>
        <button className="primary" disabled={action.isPending}>
          Save notes and tags
        </button>
      </form>
      <Feedback action={action} />
      <details>
        <summary>Experiment provenance</summary>
        <pre>
          {JSON.stringify(
            initial.manifest || { status: "No provenance recorded yet" },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}
function SaveBookmark({
  id,
  view,
  generation = null,
  agent = null,
  rightAgent = null,
}: {
  id: string;
  view: string;
  generation?: number | null;
  agent?: string | null;
  rightAgent?: string | null;
}) {
  const [open, setOpen] = useState(false),
    [title, setTitle] = useState("");
  const action = useAction();
  return (
    <div className="research-bookmark">
      <button onClick={() => setOpen(!open)}>
        <BookmarkPlus size={15} />
        Bookmark this view
      </button>
      {open && (
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            action.mutate(() =>
              research.bookmark(id, {
                title,
                view,
                generation,
                agent,
                right_agent: rightAgent,
                notes: "",
              }),
            );
          }}
        >
          <label>
            Bookmark title
            <input
              required
              maxLength={160}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <button disabled={action.isPending || !title.trim()}>
            Save bookmark
          </button>
        </form>
      )}
      <Feedback action={action} />
    </div>
  );
}
function FamilyGraph({
  data,
  selected,
  onSelect,
}: {
  data: Family;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const min = Math.max(0, data.generation - 2);
  const height = Math.max(
    360,
    Math.max(...data.nodes.map((n) => n.slot), 0) * 66 + 110,
  );
  const position = (n: AgentNode) => ({
    x: 30 + (n.generation - min) * 310,
    y: 58 + n.slot * 66,
  });
  const nodes = new Map(data.nodes.map((n) => [n.id, n]));
  return (
    <div
      className="research-graph"
      tabIndex={0}
      aria-label="Scrollable family tree"
    >
      <svg
        width="980"
        height={height}
        aria-label={`Ancestry through generation ${data.generation}`}
      >
        {[0, 1, 2].map((i) => (
          <text key={i} x={30 + i * 310} y={25} className="generation-label">
            Generation {min + i}
          </text>
        ))}
        {data.nodes.flatMap((n) =>
          n.parents.map((parent) => {
            const p = nodes.get(parent);
            if (!p) return null;
            const a = position(p),
              b = position(n);
            return (
              <path
                key={`${parent}-${n.id}`}
                d={`M${a.x + 220},${a.y + 22} C${a.x + 270},${a.y + 22} ${b.x - 50},${b.y + 22} ${b.x},${b.y + 22}`}
                className={
                  selected === n.id || selected === parent
                    ? "ancestry-edge active"
                    : "ancestry-edge"
                }
              />
            );
          }),
        )}
        {data.nodes.map((n) => {
          const p = position(n);
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              role="button"
              tabIndex={0}
              aria-label={`Agent ${n.id}, ${n.operation}`}
              onClick={() => onSelect(n.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(n.id);
                }
              }}
              className={`ancestry-node ${selected === n.id ? "chosen" : ""}`}
            >
              <rect width={220} height={46} rx={7} />
              <text x={12} y={19}>
                {n.id} · {n.operation}
              </text>
              <text x={12} y={36} className="node-sub">
                {n.fitness === null
                  ? "Not yet evaluated in this view"
                  : `Fitness ${format(n.fitness)}`}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
function Families({
  id,
  meta,
  initialGeneration,
  initialAgent,
}: {
  id: string;
  meta: ResearchMeta;
  initialGeneration?: number;
  initialAgent?: string;
}) {
  const [generation, setGeneration] = useState<number | undefined>(
      initialGeneration,
    ),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState(initialAgent || "");
  const data = useQuery({
    queryKey: [...key(id), "family", generation, offset],
    queryFn: () => research.family(id, generation, offset),
    refetchInterval: 5000,
  });
  const node = data.data?.nodes.find((n) => n.id === selected);
  return (
    <>
      <Missing id={id} meta={meta} />
      <section className="panel">
        <div className="section-title">
          <div>
            <h2>Follow the ancestry</h2>
            <p className="muted">
              Each node is an agent in a specific generation. Lines show
              recorded parents.
            </p>
          </div>
          <label>
            Through generation
            <input
              aria-label="Family generation"
              type="number"
              min={0}
              max={meta.indexed_generation ?? 0}
              value={generation ?? meta.indexed_generation ?? 0}
              onChange={(e) => {
                setGeneration(Number(e.target.value));
                setOffset(0);
              }}
            />
          </label>
        </div>
        {data.error && <p role="alert">{data.error.message}</p>}
        {data.data && (
          <>
            {data.data.nodes.length ? (
              <FamilyGraph
                data={data.data}
                selected={selected}
                onSelect={setSelected}
              />
            ) : (
              <p className="empty">No ancestry recorded for this range.</p>
            )}
            <div className="toolbar">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 200))}
              >
                Previous nodes
              </button>
              <span>
                {offset + 1}–{Math.min(offset + 200, data.data.total)} of{" "}
                {data.data.total}
              </span>
              <button
                disabled={offset + 200 >= data.data.total}
                onClick={() => setOffset(offset + 200)}
              >
                Next nodes
              </button>
            </div>
          </>
        )}
        {node && (
          <div className="research-inspector">
            <h3>Agent {node.id}</h3>
            <p>
              Operation: {node.operation} · Parents:{" "}
              {node.parents.join(", ") || "None recorded"}
            </p>
            <p>
              Weights: {node.weights_available ? "Available" : "Not retained"}
            </p>
            <p className="fingerprint">
              Fingerprint: {node.fingerprint || "Not recorded"}
            </p>
          </div>
        )}
        <SaveBookmark
          id={id}
          view="Family Trees"
          generation={generation ?? meta.indexed_generation ?? 0}
          agent={selected || null}
        />
      </section>
    </>
  );
}
function Genetics({
  id,
  meta,
  initialAgent,
  initialRight,
}: {
  id: string;
  meta: ResearchMeta;
  initialAgent?: string;
  initialRight?: string;
}) {
  const [left, setLeft] = useState(
      initialAgent || `${meta.indexed_generation ?? 0}:0`,
    ),
    [right, setRight] = useState(
      initialRight || `${meta.indexed_generation ?? 0}:1`,
    ),
    [pair, setPair] = useState<string[]>(
      initialAgent && initialRight ? [initialAgent, initialRight] : [],
    );
  const [generation, setGeneration] = useState(meta.indexed_generation ?? 0);
  const family = useQuery({
    queryKey: [...key(id), "genetic-options", generation],
    queryFn: () => research.family(id, generation),
  });
  const data = useQuery({
    queryKey: [...key(id), "genetics", pair],
    queryFn: () => research.genetics(id, pair[0], pair[1]),
    enabled: pair.length === 2,
    retry: false,
  });
  const action = useAction();
  return (
    <>
      <Missing id={id} meta={meta} />
      <section className="panel">
        <h2>Compare parameters and behavior</h2>
        <p className="muted">
          Use a generation:agent identity, such as 12:3. Parameter differences
          include the critic; behavior probes compare action probabilities.
        </p>
        <form
          className="research-controls"
          onSubmit={(e) => {
            e.preventDefault();
            setPair([left, right]);
          }}
        >
          <label>
            Browse generation
            <input
              type="number"
              min={0}
              max={meta.indexed_generation ?? 0}
              value={generation}
              onChange={(e) => setGeneration(Number(e.target.value))}
            />
          </label>
          <label>
            First agent
            <input
              list="retained-agents"
              required
              pattern="[0-9]+:[0-9]+"
              value={left}
              onChange={(e) => setLeft(e.target.value)}
            />
          </label>
          <label>
            Second agent
            <input
              list="retained-agents"
              required
              pattern="[0-9]+:[0-9]+"
              value={right}
              onChange={(e) => setRight(e.target.value)}
            />
          </label>
          <datalist id="retained-agents">
            {family.data?.nodes
              .filter((n) => n.weights_available)
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.operation}
                </option>
              ))}
          </datalist>
          <button className="primary">Compare weights</button>
          <button
            type="button"
            disabled={action.isPending || !left || !right}
            onClick={() =>
              action.mutate(() =>
                research.submit("behavior", [id], 700000, 1, [left, right]),
              )
            }
          >
            Run behavior probes
          </button>
        </form>
        <Feedback action={action} />
        {family.error && <p role="alert">{family.error.message}</p>}
        {data.error && <p role="alert">{data.error.message}</p>}
        {data.isFetching && <p>Comparing retained weights…</p>}
        {data.data && (
          <>
            <p>{data.data.note}</p>
            {data.data.layers.map((layer) => (
              <details key={layer.name} className="weight-layer" open>
                <summary>
                  {layer.name} · {layer.shape.join(" × ")}
                </summary>
                <div className="research-stat-row">
                  <span>
                    {format(layer.changed)} / {format(layer.count)} changed
                  </span>
                  <span>RMS difference {format(layer.rmse)}</span>
                  <span>
                    Largest difference {format(layer.max_absolute_difference)}
                  </span>
                </div>
                <div className="weight-grid">
                  {layer.samples.map((cell) => (
                    <div
                      key={cell.index}
                      tabIndex={0}
                      className={
                        cell.delta > 0
                          ? "weight positive"
                          : cell.delta < 0
                            ? "weight negative"
                            : "weight"
                      }
                      title={`Parameter ${cell.index}: ${cell.left} → ${cell.right}`}
                    >
                      <small>{cell.index}</small>
                      <b>{format(cell.delta)}</b>
                    </div>
                  ))}
                </div>
              </details>
            ))}
            <SaveBookmark
              id={id}
              view="Genetic Comparison"
              agent={pair[0]}
              rightAgent={pair[1]}
            />
          </>
        )}
      </section>
      <JobsPanel kind="behavior" experiment={id} />
    </>
  );
}
function EvolutionHistory({
  id,
  meta,
  initialGeneration,
}: {
  id: string;
  meta: ResearchMeta;
  initialGeneration?: number;
}) {
  const [generation, setGeneration] = useState(
      initialGeneration ?? Math.max(0, (meta.indexed_generation ?? 1) - 1),
    ),
    [playing, setPlaying] = useState(false);
  const max = Math.max(0, (meta.indexed_generation ?? 1) - 1);
  const history = useQuery({
    queryKey: [...key(id), "history"],
    queryFn: () => research.history(id),
    refetchInterval: 5000,
  });
  const detail = useQuery({
    queryKey: [...key(id), "generation", generation],
    queryFn: () => research.generation(id, generation),
  });
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(
      () => setGeneration((g) => (g >= max ? 0 : g + 1)),
      1200,
    );
    return () => window.clearInterval(timer);
  }, [playing, max]);
  const row = detail.data?.measurement;
  let distribution: number[] = [];
  try {
    distribution = JSON.parse(String(row?.population_fitness || "[]"));
  } catch {
    /* legacy data */
  }
  return (
    <>
      <Missing id={id} meta={meta} />
      <section className="panel">
        <h2>Replay the experiment’s evolution</h2>
        <p className="muted">
          Scrub committed generations to inspect the measurements available at
          that point. Game recordings remain in Spectator.
        </p>
        <div className="toolbar">
          <button
            disabled={!history.data?.total}
            onClick={() => setPlaying(!playing)}
          >
            {playing ? <Pause size={16} /> : <Play size={16} />}{" "}
            {playing ? "Pause history" : "Play history"}
          </button>
          <label>
            Generation
            <input
              aria-label="History generation"
              type="number"
              min={0}
              max={max}
              value={generation}
              onChange={(e) => {
                setPlaying(false);
                setGeneration(Number(e.target.value));
              }}
            />
          </label>
          <span>of {max}</span>
        </div>
        <input
          aria-label="Scrub evolution"
          type="range"
          min={0}
          max={max}
          value={generation}
          onChange={(e) => {
            setPlaying(false);
            setGeneration(Number(e.target.value));
          }}
        />
        {detail.error && <p role="alert">{detail.error.message}</p>}
        {row ? (
          <>
            <div className="research-metrics">
              {[
                ["Best fitness", row.best_train],
                ["Mean fitness", row.mean_train],
                ["Validation fitness", row.best_validation],
                ["Environment steps", row.environment_steps],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <span>{label}</span>
                  <strong>{format(Number(value))}</strong>
                </div>
              ))}
            </div>
            <h3>Evaluated population</h3>
            <div className="population-strip">
              {distribution.map((fitness, i) => (
                <div key={i} title={`Agent ${generation}:${i}`}>
                  <small>
                    {generation}:{i}
                  </small>
                  <strong>{format(fitness)}</strong>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="empty">
            No committed evaluation is recorded for this generation.
          </p>
        )}
        {!!meta.champions?.length && (
          <details>
            <summary>Champion selection timeline</summary>
            <div className="research-timeline">
              {meta.champions
                .filter((c) => c.generation <= generation)
                .map((c) => (
                  <button
                    key={`${c.generation}:${c.agent}`}
                    onClick={() => {
                      setPlaying(false);
                      setGeneration(c.generation);
                    }}
                  >
                    Generation {c.generation} · agent {c.agent} · validation
                    fitness {format(c.validation_fitness)}
                  </button>
                ))}
            </div>
            <p className="muted">
              Selections recorded by training, shown only through the selected
              generation.
            </p>
          </details>
        )}
        <SaveBookmark id={id} view="Evolution Replay" generation={generation} />
      </section>
      {history.error && <p role="alert">{history.error.message}</p>}
      {history.data && (
        <>
          <MetricChart
            title="Fitness through selected generation"
            rows={history.data.rows.filter(
              (r) => Number(r.generation) <= generation,
            )}
            keys={["best_train", "mean_train", "hall_of_fame"]}
          />
          {history.data.sampled && (
            <p className="muted">
              Chart is sampled: {history.data.sampling}. The selected generation
              above uses its exact saved measurement.
            </p>
          )}
        </>
      )}
    </>
  );
}
function JobResult({ job }: { job: Job }) {
  const result = job.result;
  if (!result) return null;
  const results = result.results as
    | {
        experiment: string;
        mean_fitness: number;
        std_fitness: number;
        environment_steps: number;
      }[]
    | undefined;
  return (
    <>
      {results && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Champion</th>
                <th>Mean fitness</th>
                <th>Spread</th>
                <th>Measured steps</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.experiment}>
                  <td>{r.experiment}</td>
                  <td>{format(r.mean_fitness)}</td>
                  <td>{format(r.std_fitness)}</td>
                  <td>{format(r.environment_steps)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {job.kind === "behavior" && (
        <div className="research-metrics">
          <div>
            <span>Action agreement</span>
            <strong>
              {(Number(result.action_agreement) * 100).toFixed(1)}%
            </strong>
          </div>
          <div>
            <span>Mean JS divergence</span>
            <strong>{format(Number(result.mean_js_divergence_nats))}</strong>
          </div>
          <div>
            <span>Shared probes</span>
            <strong>{String(result.probes)}</strong>
          </div>
        </div>
      )}
      {job.kind === "benchmark" && (
        <div className="research-metrics">
          <div>
            <span>Median batch latency</span>
            <strong>{format(Number(result.median_ms))} ms</strong>
          </div>
          <div>
            <span>95th percentile</span>
            <strong>{format(Number(result.p95_ms))} ms</strong>
          </div>
          <div>
            <span>Parameters</span>
            <strong>{format(Number(result.parameters))}</strong>
          </div>
        </div>
      )}
      {typeof result.note === "string" && (
        <p className="muted">{result.note}</p>
      )}
      <details>
        <summary>Protocol and complete results</summary>
        <pre>{JSON.stringify({ request: job.request, result }, null, 2)}</pre>
      </details>
    </>
  );
}
export function JobsPanel({
  kind,
  experiment,
}: {
  kind?: string;
  experiment?: string;
}) {
  const data = useQuery({
    queryKey: ["research", "jobs"],
    queryFn: research.jobs,
    refetchInterval: 2000,
  });
  const action = useAction();
  const jobs =
    data.data?.filter(
      (j) =>
        (!kind || j.kind === kind) &&
        (!experiment || j.experiments.includes(experiment)),
    ) || [];
  return (
    <section className="panel">
      <h2>Saved research jobs</h2>
      <Feedback action={action} />
      {data.error && <p role="alert">{data.error.message}</p>}
      {!jobs.length && (
        <p className="empty">
          Your analysis jobs and their results will appear here.
        </p>
      )}
      {jobs.map((job) => (
        <article className="research-job" key={job.id}>
          <div className="section-title">
            <h3>
              {job.kind} · {job.experiments.join(", ")}
            </h3>
            <span className={`badge status-${job.status}`}>{job.status}</span>
          </div>
          <p className="muted">
            {new Date(job.created * 1000).toLocaleString()}
          </p>
          {["queued", "running"].includes(job.status) ? (
            <>
              <progress value={job.progress} max={1} />
              <button
                disabled={action.isPending}
                onClick={() => action.mutate(() => research.cancel(job.id))}
              >
                Cancel job
              </button>
            </>
          ) : (
            <div className="toolbar">
              <a
                href={`/api/v1/research/jobs/${job.id}/export`}
                download
                className="button-link"
              >
                <Download size={14} /> Export results
              </a>
              <Remove
                label="Remove job"
                disabled={action.isPending}
                onConfirm={() =>
                  action.mutate(() => research.removeJob(job.id))
                }
              />
            </div>
          )}
          {job.error && (
            <p role="alert" className="error">
              {job.error}
            </p>
          )}
          <JobResult job={job} />
        </article>
      ))}
    </section>
  );
}
function Tournament({ runs, id }: { runs: Experiment[]; id: string }) {
  const [chosen, setChosen] = useState<string[]>(id ? [id] : []),
    [seed, setSeed] = useState(700000),
    [episodes, setEpisodes] = useState(8),
    [protocol, setProtocol] = useState("shared_scenarios");
  const action = useAction();
  return (
    <>
      <section className="panel">
        <h2>Tournament protocol</h2>
        <p>
          Evaluate saved champions on exactly the same scenarios. Choose
          experiments with matching games and environment settings.
        </p>
        <div className="chips">
          {runs.map((r) => (
            <label className="check" key={r.id}>
              <input
                type="checkbox"
                checked={chosen.includes(r.id)}
                disabled={!chosen.includes(r.id) && chosen.length >= 8}
                onChange={(e) =>
                  setChosen(
                    e.target.checked
                      ? [...chosen, r.id]
                      : chosen.filter((x) => x !== r.id),
                  )
                }
              />
              {r.id}
              <small>{r.config.game}</small>
            </label>
          ))}
        </div>
        <form
          className="research-controls"
          onSubmit={(e) => {
            e.preventDefault();
            action.mutate(() =>
              research.submit(
                "tournament",
                chosen,
                seed,
                episodes,
                undefined,
                protocol,
              ),
            );
          }}
        >
          <label>
            Protocol
            <select
              aria-label="Protocol"
              value={protocol}
              onChange={(e) => setProtocol(e.target.value)}
            >
              <option value="shared_scenarios">
                Shared scenarios · any game
              </option>
              <option value="rps_head_to_head">Head-to-head · RPS only</option>
            </select>
          </label>
          <label>
            First scenario seed
            <input
              type="number"
              min={0}
              max={2147483583}
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </label>
          <label>
            Scenarios per champion
            <input
              type="number"
              min={1}
              max={64}
              value={episodes}
              onChange={(e) => setEpisodes(Number(e.target.value))}
            />
          </label>
          <button
            className="primary"
            disabled={chosen.length < 2 || action.isPending}
          >
            <FlaskConical size={16} />
            Run tournament
          </button>
        </form>
        <p className="muted">
          Champions are copied when submitted. Results include every seed,
          paired differences, and actual interaction counts. These are
          exploratory comparisons, not sealed test results.
        </p>
        <Feedback action={action} />
      </section>
      <JobsPanel kind="tournament" />
    </>
  );
}
function Bookmarks({
  id,
  meta,
  onOpen,
}: {
  id: string;
  meta: ResearchMeta;
  onOpen: (bookmark: Bookmark) => void;
}) {
  const action = useAction();
  return (
    <>
      <Notebook id={id} />
      <section className="panel">
        <h2>Research bookmarks · {id}</h2>
        <Feedback action={action} />
        {!meta.bookmarks.length && (
          <p className="empty">
            Save a view from a family tree, genetic comparison, or evolution
            replay to return to it here.
          </p>
        )}
        {meta.bookmarks.map((b) => (
          <article className="research-job" key={b.id}>
            <div className="section-title">
              <h3>{b.title}</h3>
              <button onClick={() => onOpen(b)}>
                Open view <ArrowRight size={15} />
              </button>
            </div>
            <p>
              {b.view}
              {b.generation !== null ? ` · generation ${b.generation}` : ""}
              {b.agent ? ` · agent ${b.agent}` : ""}
            </p>
            {b.notes && <p>{b.notes}</p>}
            <Remove
              label="Remove bookmark"
              disabled={action.isPending}
              onConfirm={() =>
                action.mutate(() => research.deleteBookmark(id, b.id))
              }
            />
          </article>
        ))}
      </section>
    </>
  );
}
function StorageManager({ id, meta }: { id: string; meta?: ResearchMeta }) {
  const data = useQuery({
    queryKey: ["research", "storage"],
    queryFn: research.storage,
    refetchInterval: 10000,
  });
  const [weightMiB, setWeightMiB] = useState(
      (meta?.weight_bytes ?? 67108864) / 1048576,
    ),
    [replays, setReplays] = useState(false),
    [confirm, setConfirm] = useState(false);
  const action = useAction();
  useEffect(() => {
    if (meta?.weight_bytes !== undefined)
      setWeightMiB(meta.weight_bytes / 1048576);
  }, [meta?.weight_bytes]);
  return (
    <>
      <section className="panel">
        <h2>Workspace storage</h2>
        {data.error && <p role="alert">{data.error.message}</p>}
        {data.data && (
          <>
            <div className="research-metrics">
              <div>
                <span>Disk space available</span>
                <strong>{bytes(data.data.disk_free)}</strong>
              </div>
              <div>
                <span>Backups</span>
                <strong>{bytes(data.data.backup_bytes)}</strong>
              </div>
              <div>
                <span>Research jobs</span>
                <strong>{data.data.research_jobs}</strong>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Experiment</th>
                    <th>State</th>
                    <th>Total</th>
                    <th>Research history</th>
                    <th>Replays</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.runs.map((r) => (
                    <tr key={r.id}>
                      <td>{r.id}</td>
                      <td>
                        {r.status}
                        {r.archived ? " · archived" : ""}
                      </td>
                      <td>{bytes(r.bytes)}</td>
                      <td>{bytes(r.research_bytes)}</td>
                      <td>{bytes(r.replay_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      {id && (
        <section className="panel">
          <h2>Historical weight retention · {id}</h2>
          <p>
            Keep the newest parameter snapshots within this budget. Ancestry,
            notes, evaluation history, and training checkpoints are retained.
            Stop the worker before applying changes.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.mutate(() => research.retain(id, weightMiB, replays));
              setConfirm(false);
            }}
          >
            <label>
              Weight storage budget (MiB)
              <input
                type="number"
                min={0}
                max={1024}
                value={weightMiB}
                onChange={(e) => setWeightMiB(Number(e.target.value))}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={replays}
                onChange={(e) => setReplays(e.target.checked)}
              />
              Also remove captured game replays
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={confirm}
                onChange={(e) => setConfirm(e.target.checked)}
              />
              I understand removed historical weights
              {replays ? " and replays" : ""} require a backup to recover.
            </label>
            <button disabled={!confirm || action.isPending}>
              Apply retention
            </button>
          </form>
          <Feedback action={action} />
        </section>
      )}
    </>
  );
}
function Backups({ id }: { id: string }) {
  const data = useQuery({
    queryKey: ["research", "backups"],
    queryFn: research.backups,
    refetchInterval: 3000,
  });
  const [restore, setRestore] = useState(""),
    [destination, setDestination] = useState("");
  const [verified, setVerified] = useState("");
  const action = useAction();
  return (
    <>
      <section className="panel">
        <h2>Portable experiment backups</h2>
        <p>
          Back up a stopped experiment, including its checkpoints, research
          notebook, ancestry, and captured replays. Restore creates a new
          experiment and never starts training automatically.
        </p>
        <div className="toolbar">
          <button
            className="primary"
            disabled={!id || action.isPending}
            onClick={() =>
              action.mutate(() => research.submit("backup", [id], 0, 1))
            }
          >
            <Database size={16} />
            Back up {id || "selected experiment"}
          </button>
          <label className="upload-label">
            Import backup ZIP
            <input
              type="file"
              accept=".zip,application/zip"
              disabled={action.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) action.mutate(() => research.importBackup(file));
                e.target.value = "";
              }}
            />
          </label>
        </div>
        <p className="muted">
          512 MiB maximum. Imports are validated before appearing here;
          originals remain untouched.
        </p>
        <Feedback action={action} />
        {verified && (
          <p role="status">
            Verified backup {verified.slice(0, 8)}: checksums and saved model
            parameters passed.
          </p>
        )}
        {data.error && <p role="alert">{data.error.message}</p>}
        {!data.data?.length && <p className="empty">No backups saved yet.</p>}
        {data.data?.map((b) => (
          <article key={b.id} className="research-job">
            <div className="section-title">
              <h3>{b.experiment || "Invalid backup"}</h3>
              <span>{bytes(b.bytes)}</span>
            </div>
            <p className="muted">
              {b.created
                ? new Date(b.created * 1000).toLocaleString()
                : b.error}{" "}
              · {b.id.slice(0, 8)}
            </p>
            <div className="toolbar">
              <a
                className="button-link"
                href={`/api/v1/research/backups/${b.id}/download`}
                download
              >
                Download ZIP
              </a>
              <button
                disabled={action.isPending}
                onClick={() =>
                  action.mutate(async () => {
                    await research.verify(b.id);
                    setVerified(b.id);
                  })
                }
              >
                Verify backup
              </button>
              <button
                disabled={action.isPending || !!b.error}
                onClick={() => {
                  setRestore(b.id);
                  setDestination(`${b.experiment}-restored`);
                }}
              >
                Restore as new experiment
              </button>
              <Remove
                label="Remove backup"
                disabled={action.isPending}
                onConfirm={() =>
                  action.mutate(() => research.removeBackup(b.id))
                }
              />
            </div>
            {restore === b.id && (
              <form
                className="toolbar"
                onSubmit={(e) => {
                  e.preventDefault();
                  action.mutate(() => research.restore(b.id, destination));
                }}
              >
                <label>
                  Restored experiment name
                  <input
                    required
                    pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,79}"
                    maxLength={80}
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                  />
                </label>
                <button className="primary" disabled={action.isPending}>
                  Create restored experiment
                </button>
              </form>
            )}
          </article>
        ))}
      </section>
      <JobsPanel kind="backup" />
    </>
  );
}
function Resources() {
  const data = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: 3000,
  });
  const r = data.data?.resources;
  return (
    <>
      <section className="panel">
        <h2>System resources</h2>
        {data.error && <p role="alert">{data.error.message}</p>}
        {r && (
          <>
            <div className="research-metrics">
              <div>
                <span>CPU utilization</span>
                <strong>
                  {r.cpu_percent == null
                    ? "Measuring…"
                    : `${format(r.cpu_percent)}%`}
                </strong>
              </div>
              <div>
                <span>Logical processors</span>
                <strong>{r.cpu_count}</strong>
              </div>
              <div>
                <span>Memory used</span>
                <strong>
                  {r.memory_used_bytes == null
                    ? "Unavailable"
                    : bytes(r.memory_used_bytes)}
                </strong>
              </div>
              <div>
                <span>Active training workers</span>
                <strong>{data.data?.active_workers}</strong>
              </div>
            </div>
            <p>
              Load average:{" "}
              {r.load_average?.map(format).join(" / ") || "Unavailable"}
            </p>
            <p className="muted">
              Training and research analysis use CPU. One research job runs at a
              time, with one CPU thread and a three-minute analysis budget.
            </p>
          </>
        )}
      </section>
      <JobsPanel />
    </>
  );
}
function Benchmarks({ id }: { id: string }) {
  const action = useAction();
  return (
    <>
      <section className="panel">
        <h2>Measure inference performance</h2>
        <p>
          Benchmark the selected experiment’s saved champion on this machine.
          The job measures warmed CPU inference for batches of 64 observations
          and saves its configuration alongside the timings.
        </p>
        <button
          className="primary"
          disabled={!id || action.isPending}
          onClick={() =>
            action.mutate(() => research.submit("benchmark", [id], 0, 1))
          }
        >
          Benchmark {id || "selected champion"}
        </button>
        <Feedback action={action} />
      </section>
      <JobsPanel kind="benchmark" />
    </>
  );
}
export function SeedBatch({ run }: { run: Experiment }) {
  const [prefix, setPrefix] = useState(`${run.id.slice(0, 45)}-replicate`),
    [seeds, setSeeds] = useState("101, 102, 103");
  const action = useAction();
  return (
    <details className="panel">
      <summary>Create a batch of independent seeds</summary>
      <p>
        Copy this experiment’s configuration into up to eight fresh runs. Review
        and start them from Experiments.
      </p>
      <form
        className="research-controls"
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate(() =>
            research.batch(
              prefix,
              seeds.split(",").map((s) => Number(s.trim())),
              run.config,
            ),
          );
        }}
      >
        <label>
          Name prefix
          <input
            required
            maxLength={60}
            pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,59}"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
          />
        </label>
        <label>
          Seeds, separated by commas
          <input
            required
            value={seeds}
            onChange={(e) => setSeeds(e.target.value)}
          />
        </label>
        <button disabled={action.isPending}>Create seed batch</button>
      </form>
      <Feedback action={action} />
    </details>
  );
}
export function ResearchPage({
  page,
  runs,
  id,
  initialGeneration,
  initialAgent,
  initialRight,
  onOpen,
}: {
  page: string;
  runs: Experiment[];
  id: string;
  initialGeneration?: number;
  initialAgent?: string;
  initialRight?: string;
  onOpen: (b: Bookmark) => void;
}) {
  const meta = useQuery({
    queryKey: [...key(id), "meta"],
    queryFn: () => research.meta(id),
    enabled: !!id,
    refetchInterval: 5000,
  });
  if (page === "System Resources") return <Resources />;
  if (page === "Backups") return <Backups id={id} />;
  if (page === "Storage Manager")
    return <StorageManager id={id} meta={meta.data} />;
  if (page === "Benchmarks") return <Benchmarks id={id} />;
  if (page === "Tournament Lab") return <Tournament runs={runs} id={id} />;
  if (page === "Compare Runs")
    return (
      <>
        <Analytics runs={runs} selected={id} />
        {runs.find((r) => r.id === id) && (
          <SeedBatch run={runs.find((r) => r.id === id)!} />
        )}
      </>
    );
  if (!id)
    return (
      <section className="panel empty">
        Create or select an experiment to explore its research workspace.
      </section>
    );
  if (meta.error) return <p role="alert">{meta.error.message}</p>;
  if (!meta.data) return <p>Loading research workspace…</p>;
  if (page === "Family Trees")
    return (
      <Families
        id={id}
        meta={meta.data}
        initialGeneration={initialGeneration}
        initialAgent={initialAgent}
      />
    );
  if (page === "Genetic Comparison")
    return (
      <Genetics
        id={id}
        meta={meta.data}
        initialAgent={initialAgent}
        initialRight={initialRight}
      />
    );
  if (page === "Evolution Replay")
    return (
      <EvolutionHistory
        id={id}
        meta={meta.data}
        initialGeneration={initialGeneration}
      />
    );
  return <Bookmarks id={id} meta={meta.data} onOpen={onOpen} />;
}
