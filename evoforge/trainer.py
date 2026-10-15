"""Reproducible universal trainer; checkpoints are generation commit records."""

import csv
import io
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from .agents import policy_for
from .agents.serialization import export_policy
from .algorithms import crossover, evaluate_details, mutate, ppo_refine
from .core.checkpoints import atomic_bytes, atomic_json, load_recovering, save
from .games import available_games, close_env, game_version, make_env


class TrainingStopped(Exception):
    """Cooperative interruption. Only committed generations survive recovery."""


@dataclass
class Config:
    mode: str = "hybrid"
    game: str = "snake"
    population: int = 24
    generations: int = 20
    elites: int = 2
    ppo_candidates: int = 3
    ppo_episodes: int = 4
    eval_episodes: int = 3
    size: int = 10
    max_steps: int = 300
    seed: int = 42
    mutation_probability: float = 0.05
    mutation_sigma: float = 0.08
    hidden: int | list[int] = 64
    game_config: dict = field(default_factory=dict)
    environment_step_budget: int | None = None

    def validate(self):
        if self.game not in available_games():
            raise ValueError(f"Unknown installed game: {self.game}")
        if self.mode not in ("evolution", "hybrid", "ppo"):
            raise ValueError("mode must be evolution, hybrid or ppo")
        for key in (
            "population",
            "generations",
            "elites",
            "ppo_candidates",
            "ppo_episodes",
            "eval_episodes",
            "size",
            "max_steps",
            "seed",
        ):
            if not isinstance(getattr(self, key), int) or isinstance(getattr(self, key), bool):
                raise ValueError(f"{key} must be an integer")
        if self.population < 2 or not 1 <= self.elites < self.population:
            raise ValueError("need population>=2 and 1<=elites<population")
        if (
            min(self.generations, self.eval_episodes, self.ppo_episodes, self.max_steps) < 1
            or self.seed < 0
        ):
            raise ValueError("episode/generation/step counts must be positive; seed nonnegative")
        if not 0 <= self.ppo_candidates <= self.population:
            raise ValueError("invalid ppo_candidates")
        if (
            not (0 <= self.mutation_probability <= 1)
            or not np.isfinite(self.mutation_sigma)
            or self.mutation_sigma < 0
        ):
            raise ValueError("invalid mutation settings")
        if self.environment_step_budget is not None and (
            not isinstance(self.environment_step_budget, int) or self.environment_step_budget < 1
        ):
            raise ValueError("environment_step_budget must be a positive integer")
        json.dumps(self.game_config, allow_nan=False)
        env = make_env(self.game, self.size, self.max_steps, self.game_config)
        close_env(env)
        widths = [self.hidden] if isinstance(self.hidden, int) else self.hidden
        if (
            not isinstance(widths, list)
            or not widths
            or any(not isinstance(n, int) or n < 1 for n in widths)
        ):
            raise ValueError("hidden must be a positive integer or list of positive widths")


class Trainer:
    def __init__(
        self, config, directory, resume=False, control=None, telemetry=None, managed=False
    ):
        self.cfg = config
        self.cfg.validate()
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self.dir / "checkpoint.pt"
        if not resume and self.checkpoint.exists():
            raise ValueError("Checkpoint exists: use resume or create a new experiment")
        self.control, self.telemetry, self.managed = control, telemetry, managed
        self.rng = np.random.default_rng(config.seed)
        torch.manual_seed(config.seed)
        random.seed(config.seed)
        self.generation = self.environment_steps = 0
        self.wall_seconds = 0.0
        self.checkpoint_recovered = False
        self.population = [self._policy() for _ in range(config.population)]
        self.optimizer_states = [None] * config.population
        self.champion_score = float("-inf")
        self.champion = None
        self.champion_history = []
        self.history = []
        self.lineage = []
        self.plugin_version = game_version(config.game)
        from .research.provenance import manifest

        self.research_manifest = manifest(config)
        if resume:
            self._load()
            self._sync_artifacts()
        atomic_json(self.dir / "config.json", asdict(self.cfg))

    def _policy(self):
        return policy_for(
            self.cfg.game, self.cfg.hidden, self.cfg.game_config, self.cfg.size, self.cfg.max_steps
        )

    def _save(self):
        save(
            self.checkpoint,
            {
                "config": asdict(self.cfg),
                "generation": self.generation,
                "architecture": self.population[0].architecture,
                "plugin_version": self.plugin_version,
                "algorithm_version": 1,
                "research_manifest": self.research_manifest,
                "population": [m.state_dict() for m in self.population],
                "optimizer_states": self.optimizer_states,
                "champion": self.champion.state_dict() if self.champion else None,
                "champion_score": self.champion_score,
                "champion_history": self.champion_history,
                "numpy_state": self.rng.bit_generator.state,
                "torch_state": torch.get_rng_state(),
                "python_state": random.getstate(),
                "history": self.history,
                "environment_steps": self.environment_steps,
                "wall_seconds": self.wall_seconds,
                "lineage": self.lineage,
            },
        )

    def _load(self):
        data, self.checkpoint_recovered = load_recovering(self.checkpoint)
        old_config = asdict(Config(**data["config"]))
        current = asdict(self.cfg)
        old_config.pop("generations")
        current.pop("generations")
        if old_config != current:
            raise ValueError("resume config differs from checkpoint; only generations may change")
        if data.get("plugin_version", self.plugin_version) != self.plugin_version:
            raise ValueError("Plugin version differs from checkpoint; explicit migration required")
        if (
            data.get("architecture", self.population[0].architecture)
            != self.population[0].architecture
        ):
            raise ValueError("Checkpoint architecture incompatible with game/configuration")
        if len(data["population"]) != len(self.population):
            raise ValueError("Checkpoint population count does not match configuration")
        recorded = data.get("research_manifest")
        if recorded and recorded.get("environment") != self.research_manifest["environment"]:
            raise ValueError(
                "Environment content differs from checkpoint; restore the original environment"
            )
        if recorded:
            self.research_manifest = recorded
        else:
            self.research_manifest["provenance"] = (
                "Legacy checkpoint: original environment content was not recorded"
            )
        self.generation = data["generation"]
        try:
            for model, state in zip(self.population, data["population"]):
                model.load_state_dict(state)
            if data["champion"] is not None:
                self.champion = self._policy()
                self.champion.load_state_dict(data["champion"])
        except RuntimeError as exc:
            raise ValueError(f"Checkpoint architecture incompatible: {exc}") from exc
        self.champion_score = data["champion_score"]
        self.optimizer_states = data.get("optimizer_states", [None] * self.cfg.population)
        self.champion_history = data.get("champion_history", [])
        self.lineage = data.get("lineage", [])
        self.environment_steps = data.get("environment_steps", 0)
        self.wall_seconds = data.get("wall_seconds", 0.0)
        # Legacy metrics after the last commit are discarded, never duplicated.
        if "history" in data:
            self.history = data["history"]
        else:
            from .service import read_metrics

            self.history = [
                r for r in read_metrics(self.dir) if int(r["generation"]) < self.generation
            ]
        self.rng.bit_generator.state = data["numpy_state"]
        torch.set_rng_state(data["torch_state"])
        random.setstate(data["python_state"])

    def _append_metric(self, record):
        from .service import read_metrics

        rows = [r for r in read_metrics(self.dir) if int(r["generation"]) != record["generation"]]
        self._write_metrics([*rows, record])

    def _write_metrics(self, rows):
        fields = list(dict.fromkeys(key for row in rows for key in row))
        if not fields:
            return
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        atomic_bytes(self.dir / "metrics.csv", stream.getvalue().encode())

    def _sync_artifacts(self):
        if self.checkpoint_recovered and (self.dir / "metrics.csv").exists():
            original = self.dir / "metrics.csv.pre-recovery"
            if not original.exists():
                atomic_bytes(original, (self.dir / "metrics.csv").read_bytes())
        self._write_metrics(self.history)
        if not self.history and (self.dir / "metrics.csv").exists():
            # Preserve discarded rows for operator inspection before reconciliation.
            path = self.dir / "metrics.csv"
            if not path.with_suffix(".csv.pre-recovery").exists():
                atomic_bytes(path.with_suffix(".csv.pre-recovery"), path.read_bytes())
            atomic_bytes(path, b"")
        if self.champion:
            export_policy(
                self.dir / "champion.pt",
                self.champion,
                asdict(self.cfg),
                validation_score=self.champion_score,
            )
        save(
            self.dir / "spectator.pt",
            {
                "config": asdict(self.cfg),
                "generation": self.generation,
                "architecture": self.population[0].architecture,
                "policies": [m.state_dict() for m in self.population[:9]],
            },
            backup=False,
        )
        self._sync_research()
        # Optional sink belongs to storage/supervisor; engine has no UI/API dependency.
        if getattr(self, "on_commit", None):
            self.on_commit(self)

    def _sync_research(self):
        from .research.store import ResearchStore

        ResearchStore(self.dir).sync(
            {
                "config": asdict(self.cfg),
                "generation": self.generation,
                "architecture": self.population[0].architecture,
                "population": [m.state_dict() for m in self.population],
                "lineage": self.lineage,
                "history": self.history,
                "research_manifest": self.research_manifest,
                "champion_history": self.champion_history,
            }
        )

    def _step(self, env, episode, reward, terminated, truncated):
        self.environment_steps += 1
        if self.control:
            self.control()
        if self.telemetry:
            self.telemetry(
                env,
                episode,
                reward,
                terminated,
                truncated,
                self.generation,
                getattr(self, "_agent", 0),
                getattr(self, "_phase", "training"),
            )

    def _evaluate(self, model, seeds, phase="training", agent=0):
        self._phase, self._agent = phase, agent
        return evaluate_details(
            model,
            seeds,
            self.cfg.size,
            self.cfg.max_steps,
            game=self.cfg.game,
            game_config=self.cfg.game_config,
            on_step=self._step,
        )

    def _refine(self, model, optimizer_state=None):
        self._phase = "ppo"
        improved = ppo_refine(
            model,
            int(self.rng.integers(2**31)),
            self.cfg.ppo_episodes,
            self.cfg.size,
            self.cfg.max_steps,
            game=self.cfg.game,
            game_config=self.cfg.game_config,
            optimizer_state=optimizer_state,
            on_step=self._step,
        )
        return improved

    def run(self):
        if not self.checkpoint.exists():
            self._save()
            self._sync_research()
        self._worker_status("running")
        try:
            for g in range(self.generation, self.cfg.generations):
                if (
                    self.cfg.environment_step_budget
                    and self.environment_steps >= self.cfg.environment_step_budget
                ):
                    break
                if self.control:
                    self.control()
                started = time.perf_counter()
                self._worker_status("running", generation=g)
                seeds = self.rng.integers(0, 2**31, size=self.cfg.eval_episodes)
                results = [self._evaluate(m, seeds, agent=i) for i, m in enumerate(self.population)]
                evaluation_seconds = time.perf_counter() - started
                scores = [r["fitness"] for r in results]
                order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
                candidate = self.population[order[0]]
                validation = self._evaluate(
                    candidate,
                    [self.cfg.seed + 900000 + i for i in range(12)],
                    "validation",
                    order[0],
                )
                if validation["fitness"] > self.champion_score:
                    self.champion = candidate.clone()
                    self.champion_score = validation["fitness"]
                    self.champion_history.append(
                        {
                            "generation": g,
                            "validation_fitness": self.champion_score,
                            "agent": order[0],
                        }
                    )
                ppo_stats = []
                if self.cfg.mode == "ppo":
                    next_population, optimizers = [], []
                    for i, model in enumerate(self.population):
                        self._agent = i
                        improved = self._refine(model, self.optimizer_states[i])
                        next_population.append(improved)
                        optimizers.append(improved.optimizer_state)
                        ppo_stats.append(improved.training_stats)
                        self.lineage.append(
                            {"generation": g + 1, "agent": i, "parents": [i], "operation": "ppo"}
                        )
                else:
                    parents = [self.population[i] for i in order]
                    next_population = [parents[i].clone() for i in range(self.cfg.elites)]
                    lineage = [
                        {
                            "generation": g + 1,
                            "agent": i,
                            "parents": [order[i]],
                            "operation": "elite",
                        }
                        for i in range(self.cfg.elites)
                    ]
                    if self.cfg.mode == "hybrid":
                        for i in range(self.cfg.ppo_candidates):
                            self._agent = order[i]
                            improved = self._refine(parents[i])
                            ppo_stats.append(improved.training_stats)
                            check = self.rng.integers(0, 2**31, size=max(3, self.cfg.eval_episodes))
                            if (
                                self._evaluate(improved, check, "acceptance")["fitness"]
                                >= self._evaluate(parents[i], check, "acceptance")["fitness"]
                            ):
                                if len(next_population) < self.cfg.population:
                                    lineage.append(
                                        {
                                            "generation": g + 1,
                                            "agent": len(next_population),
                                            "parents": [order[i]],
                                            "operation": "ppo",
                                        }
                                    )
                                    next_population.append(improved)
                    pool_size = max(2, len(parents) // 3)
                    while len(next_population) < self.cfg.population:
                        a_index = int(self.rng.integers(pool_size))
                        parent = parents[a_index]
                        ancestors = [order[a_index]]
                        if self.rng.random() < 0.3:
                            b_index = int(self.rng.integers(pool_size))
                            parent = crossover(parent, parents[b_index], self.rng)
                            ancestors.append(order[b_index])
                        lineage.append(
                            {
                                "generation": g + 1,
                                "agent": len(next_population),
                                "parents": ancestors,
                                "operation": "mutation",
                            }
                        )
                        next_population.append(
                            mutate(
                                parent,
                                self.rng,
                                self.cfg.mutation_probability,
                                self.cfg.mutation_sigma,
                            )
                        )
                    self.lineage.extend(lineage)
                    optimizers = [None] * self.cfg.population
                self.population, self.optimizer_states = next_population, optimizers
                seconds = time.perf_counter() - started
                self.wall_seconds += seconds
                record = {
                    "generation": g,
                    "best_score": results[order[0]]["score"],
                    "mean_score": float(np.mean([r["score"] for r in results])),
                    "validation_score": validation["score"],
                    "learning_reward_mean": float(np.mean([r["reward"] for r in results])),
                    "best_food": results[order[0]]["score"],
                    "validation_food": validation["score"],
                    "best_train": max(scores),
                    "mean_train": float(np.mean(scores)),
                    "best_validation": validation["fitness"],
                    "hall_of_fame": self.champion_score,
                    "median_train": float(np.median(scores)),
                    "std_train": float(np.std(scores)),
                    "fitness_gap": float(max(scores) - np.mean(scores)),
                    "fitness_spread": float(np.ptp(scores)),
                    "population_fitness": json.dumps(scores),
                    "environment_steps": self.environment_steps,
                    "ppo_refinements": len(ppo_stats),
                    "ppo_steps": sum(r["steps"] for r in ppo_stats),
                    "ppo_loss": float(np.mean([r["loss"] for r in ppo_stats]))
                    if ppo_stats
                    else 0.0,
                    "evaluation_seconds": evaluation_seconds,
                    "total_seconds": seconds,
                    "wall_seconds": self.wall_seconds,
                    "steps_per_second": self.environment_steps / max(self.wall_seconds, 1e-9),
                }
                self.history.append(record)
                self.generation = g + 1
                self._save()  # Commit before materializing CSV/champion/database.
                self._sync_artifacts()
                print(json.dumps(record), flush=True)
                with (self.dir / "timings.jsonl").open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "generation": g,
                                **{
                                    k: record[k]
                                    for k in (
                                        "evaluation_seconds",
                                        "ppo_refinements",
                                        "total_seconds",
                                    )
                                },
                            }
                        )
                        + "\n"
                    )
        except TrainingStopped:
            self._worker_status("stopped")
            return "stopped"
        self._worker_status("complete", generation=self.generation)
        return "completed"

    def _worker_status(self, state, generation=None):
        if self.managed:
            return
        atomic_json(
            self.dir / "worker.json",
            {
                "pid": os.getpid(),
                "state": state,
                "generation": self.generation if generation is None else generation,
                "target_generations": self.cfg.generations,
                "updated_at": time.time(),
            },
        )
