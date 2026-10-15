import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  BarChart,
  Bar,
} from "recharts";
import { api } from "./api";
import type { Experiment, Metric } from "./types";
const colors = ["#a9dc81", "#e7ad75", "#75b7bc", "#c49bdd"];
export function MetricChart({
  rows,
  keys,
  title,
  x = "generation",
}: {
  rows: Metric[];
  keys: string[];
  title: string;
  x?: string;
}) {
  const available = keys.filter((key) =>
    rows.some((row) => row[key] !== undefined && row[key] !== null),
  );
  return (
    <section className="panel chart-panel">
      <h3>{title}</h3>
      {!rows.length || !available.length ? (
        <p className="empty">No measured data available yet.</p>
      ) : (
        <div className="chart" role="img" aria-label={title}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis
                dataKey={x}
                stroke="var(--muted)"
                tickLine={false}
                fontSize={11}
              />
              <YAxis
                stroke="var(--muted)"
                tickLine={false}
                fontSize={11}
                width={45}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--panel)",
                  borderColor: "var(--line)",
                  borderRadius: 10,
                }}
              />
              <Legend />
              {available.map((key, i) => (
                <Line
                  key={key}
                  type="linear"
                  dataKey={key}
                  stroke={colors[i % colors.length]}
                  dot={false}
                  strokeWidth={2}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
export function Analytics({
  runs,
  selected,
}: {
  runs: Experiment[];
  selected: string;
}) {
  const [ids, setIds] = useState<string[]>([]);
  const [axis, setAxis] = useState("generation");
  const [budget, setBudget] = useState("");
  const chosen = ids.length ? ids : selected ? [selected] : [];
  const queries = useQueries({
    queries: chosen.map((id) => ({
      queryKey: ["metrics", id],
      queryFn: () => api.metrics(id),
      refetchInterval: 3000,
    })),
  });
  const comparison = useQuery({
    queryKey: ["compare", chosen, budget],
    queryFn: () => api.compare(chosen, budget ? Number(budget) : undefined),
    enabled: chosen.length >= 2,
    retry: false,
  });
  const history = queries[0]?.data || [];
  const last = history.at(-1);
  let distribution: number[] = [];
  try {
    distribution = JSON.parse(String(last?.population_fitness || "[]"));
  } catch {
    /* Legacy histories may omit distributions. */
  }
  return (
    <>
      <div className="panel">
        <div className="section-title">
          <h2>Compare measured performance</h2>
          <label>
            Horizontal axis
            <select
              aria-label="Horizontal axis"
              value={axis}
              onChange={(e) => setAxis(e.target.value)}
            >
              <option value="generation">Generation</option>
              <option value="environment_steps">Environment steps</option>
            </select>
          </label>
        </div>
        <div className="chips">
          {runs.map((r) => (
            <label className="check" key={r.id}>
              <input
                type="checkbox"
                checked={chosen.includes(r.id)}
                onChange={(e) =>
                  setIds(
                    e.target.checked
                      ? [...chosen, r.id]
                      : chosen.filter((x) => x !== r.id),
                  )
                }
              />
              {r.id}
            </label>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Experiment</th>
                <th>Game / version</th>
                <th>Algorithm</th>
                <th>Seed</th>
                <th>Step budget</th>
                <th>Reward scale</th>
              </tr>
            </thead>
            <tbody>
              {runs
                .filter((r) => chosen.includes(r.id))
                .map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>
                      {r.config.game} / {r.game_version}
                    </td>
                    <td>{r.config.mode}</td>
                    <td>{r.config.seed}</td>
                    <td>{r.config.environment_step_budget ?? "Unlimited"}</td>
                    <td>Plugin-defined; compare identical environments</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <label>
          Matched environment-step budget
          <input
            type="number"
            min={1}
            placeholder="Common measured budget"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
          />
        </label>
        {comparison.error && (
          <p role="alert" className="error">
            {comparison.error.message}
          </p>
        )}
        {comparison.data && (
          <>
            <p>{comparison.data.note}</p>
            <pre>{JSON.stringify(comparison.data.results, null, 2)}</pre>
          </>
        )}
      </div>
      {queries.some((q) => q.isError) && (
        <p role="alert">
          Metrics could not be loaded.{" "}
          {queries.find((q) => q.error)?.error?.message}
        </p>
      )}
      {chosen.length > 1 && (
        <div className="grid-two">
          {chosen.map((id, i) => (
            <MetricChart
              key={id}
              title={`${id} · best fitness`}
              rows={queries[i].data || []}
              keys={["best_train", "best_validation"]}
              x={axis}
            />
          ))}
        </div>
      )}
      <div className="grid-two">
        <MetricChart
          rows={history}
          keys={["best_train", "mean_train", "median_train"]}
          title="Population fitness"
          x={axis}
        />
        <MetricChart
          rows={history}
          keys={["best_validation", "hall_of_fame"]}
          title="Validation & champion history"
          x={axis}
        />
        <MetricChart
          rows={history}
          keys={["environment_steps"]}
          title="Environment interactions"
        />
        <MetricChart
          rows={history}
          keys={["steps_per_second"]}
          title="Training throughput"
          x={axis}
        />
        <MetricChart
          rows={history}
          keys={["total_seconds", "evaluation_seconds"]}
          title="Generation duration (seconds)"
          x={axis}
        />
        <MetricChart
          rows={history.filter((r) => Number(r.ppo_refinements) > 0)}
          keys={["ppo_loss"]}
          title="PPO loss · where available"
          x={axis}
        />
        <MetricChart
          rows={history.filter((r) => Number(r.ppo_refinements) > 0)}
          keys={["ppo_steps"]}
          title="PPO steps · where available"
          x={axis}
        />
        <section className="panel">
          <h3>Latest population distribution</h3>
          {distribution.length ? (
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={distribution.map((fitness, agent) => ({
                    agent,
                    fitness,
                  }))}
                >
                  <XAxis dataKey="agent" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="fitness" fill="#a9dc81" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="empty">Population scores are not available.</p>
          )}
        </section>
      </div>
    </>
  );
}
