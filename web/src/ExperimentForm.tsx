import { useState, type FormEvent } from "react";
import type { Config, Game } from "./types";
export const defaults: Config = {
  game: "snake",
  mode: "hybrid",
  population: 24,
  generations: 20,
  elites: 2,
  ppo_candidates: 3,
  ppo_episodes: 4,
  eval_episodes: 3,
  size: 10,
  max_steps: 300,
  seed: 42,
  hidden: 64,
  mutation_probability: 0.05,
  mutation_sigma: 0.08,
  game_config: {},
  environment_step_budget: null,
};
const fields: [keyof Config, string, number, number, number?][] = [
  ["population", "Population size", 2, 4096],
  ["generations", "Generations", 1, 1000000],
  ["elites", "Elite count", 1, 4095],
  ["ppo_candidates", "PPO candidates", 0, 4096],
  ["ppo_episodes", "PPO episodes", 1, 10000],
  ["eval_episodes", "Evaluation episodes", 1, 10000],
  ["size", "Board size", 5, 128],
  ["max_steps", "Maximum episode steps", 1, 100000],
  ["seed", "Random seed", 0, 2147483647],
  ["mutation_probability", "Mutation probability", 0, 1, 0.01],
  ["mutation_sigma", "Mutation sigma", 0, 100, 0.01],
];
export function ExperimentForm({
  games,
  onSubmit,
  onCancel,
  pending,
  error,
}: {
  games: Game[];
  onSubmit: (id: string, config: Config) => void;
  onCancel: () => void;
  pending: boolean;
  error?: string;
}) {
  const [config, setConfig] = useState<Config>({
    ...defaults,
    game: games[0]?.id || "snake",
  });
  const [name, setName] = useState("");
  const [hidden, setHidden] = useState("64");
  const [json, setJson] = useState("{}");
  const [invalid, setInvalid] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const widths = hidden.split(",").map(Number);
      if (
        widths.length > 8 ||
        widths.some((x) => !Number.isInteger(x) || x < 1 || x > 1024)
      )
        throw Error("Hidden widths: enter 1–8 integers between 1 and 1024.");
      const game_config = JSON.parse(json);
      if (
        !game_config ||
        Array.isArray(game_config) ||
        typeof game_config !== "object"
      )
        throw Error("Game configuration must be a JSON object.");
      if (config.elites >= config.population)
        throw Error("Elite count must be less than population size.");
      if (config.ppo_candidates > config.population)
        throw Error("PPO candidates cannot exceed population size.");
      setInvalid("");
      onSubmit(name, { ...config, hidden: widths, game_config });
    } catch (e) {
      setInvalid((e as Error).message);
    }
  }
  return (
    <section className="panel" aria-label="Create experiment">
      <div className="section-title">
        <div>
          <span className="eyebrow">NEW EXPERIMENT</span>
          <h2>Set the conditions. See what evolves.</h2>
        </div>
        <button onClick={onCancel}>Cancel</button>
      </div>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label>
            Experiment name
            <input
              required
              pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,79}"
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="coin-exploration"
              autoFocus
            />
          </label>
          <label>
            Game
            <select
              aria-label="Game"
              value={config.game}
              onChange={(e) => setConfig({ ...config, game: e.target.value })}
            >
              {games.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Algorithm
            <select
              aria-label="Algorithm"
              value={config.mode}
              onChange={(e) => setConfig({ ...config, mode: e.target.value })}
            >
              {["evolution", "ppo", "hybrid"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          {fields.map(([key, label, min, max, step]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                required
                min={min}
                max={max}
                step={step || 1}
                value={config[key] as number}
                onChange={(e) =>
                  setConfig({ ...config, [key]: Number(e.target.value) })
                }
              />
            </label>
          ))}
          <label>
            Hidden widths
            <input
              value={hidden}
              onChange={(e) => setHidden(e.target.value)}
              placeholder="64,64"
              required
            />
          </label>
          <label>
            Environment interaction budget
            <input
              type="number"
              min={1}
              value={config.environment_step_budget ?? ""}
              onChange={(e) =>
                setConfig({
                  ...config,
                  environment_step_budget: e.target.value
                    ? Number(e.target.value)
                    : null,
                })
              }
              placeholder="Unlimited"
            />
          </label>
        </div>
        <label>
          Game-specific JSON configuration
          <textarea
            value={json}
            onChange={(e) => setJson(e.target.value)}
            rows={3}
          />
        </label>
        <p className="muted">
          Coin supports <code>{'{"horizon":12}'}</code>. Built-in Snake and
          Flappy use board size and maximum steps.
        </p>
        {(invalid || error) && (
          <p role="alert" className="error">
            {invalid || error}
          </p>
        )}
        <button className="primary" disabled={pending} type="submit">
          {pending ? "Creating…" : "Create experiment"}
        </button>
      </form>
    </section>
  );
}
