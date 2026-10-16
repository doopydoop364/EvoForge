"""Numeric and behavioral comparisons, with explicit probes and measured budgets."""

import time

import numpy as np
import torch

from evoforge.algorithms import evaluate_details
from evoforge.games import close_env, make_env, transition
from evoforge.policy import Policy


def model_from_snapshot(data):
    model = Policy(**data["architecture"])
    model.load_state_dict(data["state_dict"], strict=True)
    model.eval()
    return model


def snapshot(store, identifier, config):
    descriptor, values, row = store.weights(identifier)
    state = {
        part["name"]: torch.from_numpy(
            values[part["offset"] : part["offset"] + part["count"]].copy()
        ).reshape(part["shape"])
        for part in descriptor["layout"]
    }
    return {
        "architecture": descriptor["architecture"],
        "state_dict": state,
        "config": config,
        "fingerprint": row["fingerprint"],
        "node": identifier,
    }


def genetic_comparison(store, left, right):
    a, av, ar = store.weights(left)
    b, bv, br = store.weights(right)
    if a != b:
        raise ValueError("Genetic comparison requires matching parameter layouts")
    layers = []
    for part in a["layout"]:
        x = av[part["offset"] : part["offset"] + part["count"]].astype(np.float64)
        y = bv[part["offset"] : part["offset"] + part["count"]].astype(np.float64)
        delta = y - x
        indices = np.unique(np.linspace(0, max(0, len(x) - 1), min(96, len(x)), dtype=int))
        layers.append(
            {
                "name": part["name"],
                "shape": part["shape"],
                "count": len(x),
                "changed": int(np.count_nonzero(delta)),
                "rmse": float(np.sqrt(np.mean(delta**2))),
                "max_absolute_difference": float(np.max(np.abs(delta))),
                "samples": [
                    {
                        "index": int(i),
                        "left": float(x[i]),
                        "right": float(y[i]),
                        "delta": float(delta[i]),
                    }
                    for i in indices
                ],
            }
        )
    return {
        "left": left,
        "right": right,
        "left_fingerprint": ar["fingerprint"],
        "right_fingerprint": br["fingerprint"],
        "layers": layers,
        "note": "Full layer statistics; at most 96 displayed cells per layer. Parameter distance does not establish behavioral similarity.",
    }


def behavior(inputs, seed, check):
    models = [model_from_snapshot(d) for d in inputs]
    config = inputs[0]["config"]
    env = make_env(config["game"], config["size"], config["max_steps"], config.get("game_config"))
    rng = np.random.default_rng(seed)
    probes = []
    try:
        obs = env.reset(seed)
        for _ in range(128):
            check()
            probes.append(np.asarray(obs, dtype=np.float32).copy())
            obs, _, term, trunc, _ = transition(env, int(rng.integers(env.action_size)))
            if term or trunc:
                obs = env.reset(int(rng.integers(2**31)))
    finally:
        close_env(env)
    with torch.no_grad():
        distributions = [
            torch.softmax(m(torch.from_numpy(np.stack(probes)))[0], dim=-1).numpy() for m in models
        ]
    a, b = distributions
    midpoint = (a + b) / 2
    js = (
        np.sum(a * np.log(np.maximum(a, 1e-20) / np.maximum(midpoint, 1e-20)), axis=1)
        + np.sum(b * np.log(np.maximum(b, 1e-20) / np.maximum(midpoint, 1e-20)), axis=1)
    ) / 2
    return {
        "seed": seed,
        "probes": len(probes),
        "probe_policy": "seeded uniform random actions in the recorded environment",
        "action_agreement": float(np.mean(a.argmax(1) == b.argmax(1))),
        "mean_js_divergence_nats": float(js.mean()),
        "samples": [
            {"observation": obs.tolist(), "left": x.tolist(), "right": y.tolist()}
            for obs, x, y in zip(probes[:16], a[:16], b[:16])
        ],
        "note": "Similarity on these probes only; not a measure of learning quality.",
    }


def tournament(inputs, seed, episodes, check, progress):
    seeds = list(range(seed, seed + episodes))
    rows = []
    models = [model_from_snapshot(d) for d in inputs]
    started = time.perf_counter()
    for i, (data, model) in enumerate(zip(inputs, models)):
        cfg = data["config"]
        trials = []
        for j, episode_seed in enumerate(seeds):
            check()
            trial = evaluate_details(
                model,
                [episode_seed],
                cfg["size"],
                cfg["max_steps"],
                game=cfg["game"],
                game_config=cfg.get("game_config"),
                on_step=lambda *_: check(),
            )
            trials.append({"seed": episode_seed, **trial})
            progress((i * episodes + j + 1) / (len(inputs) * episodes))
        scores = [t["fitness"] for t in trials]
        rows.append(
            {
                "experiment": data["experiment"],
                "fingerprint": data["fingerprint"],
                "mean_fitness": float(np.mean(scores)),
                "std_fitness": float(np.std(scores)),
                "environment_steps": sum(t["steps"] for t in trials),
                "trials": trials,
            }
        )
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            diff = np.array(
                [a["fitness"] - b["fitness"] for a, b in zip(rows[i]["trials"], rows[j]["trials"])]
            )
            pairs.append(
                {
                    "left": rows[i]["experiment"],
                    "right": rows[j]["experiment"],
                    "mean_difference": float(diff.mean()),
                    "wins": int(np.sum(diff > 0)),
                    "ties": int(np.sum(diff == 0)),
                    "losses": int(np.sum(diff < 0)),
                }
            )
    return {
        "protocol": "shared-scenario champion tournament",
        "seeds": seeds,
        "results": sorted(rows, key=lambda r: r["mean_fitness"], reverse=True),
        "pairs": pairs,
        "wall_seconds": time.perf_counter() - started,
        "note": "Exploratory deterministic evaluations on common seeds, not head-to-head games or a sealed test. Repeated seeds are not independent training runs.",
    }


def benchmark(data, check):
    model = model_from_snapshot(data)
    probes = torch.zeros((64, model.architecture["input_size"]), dtype=torch.float32)
    with torch.no_grad():
        for _ in range(20):
            model(probes)
        elapsed = []
        for _ in range(200):
            check()
            start = time.perf_counter_ns()
            model(probes)
            elapsed.append((time.perf_counter_ns() - start) / 1e6)
    return {
        "kind": "CPU inference",
        "batch_size": 64,
        "warmup_batches": 20,
        "measured_batches": 200,
        "median_ms": float(np.median(elapsed)),
        "p95_ms": float(np.percentile(elapsed, 95)),
        "parameters": sum(p.numel() for p in model.parameters()),
        "torch": str(torch.__version__),
        "threads": torch.get_num_threads(),
        "note": "Synthetic zero observations; excludes environment, storage and training costs.",
    }


def rps_tournament(inputs, seed, episodes, check, progress):
    """Simultaneous deterministic decisions; equal seeded histories for both players."""
    models = [model_from_snapshot(data) for data in inputs]
    if any(data["config"]["game"] != "rps" for data in inputs):
        raise ValueError("Head-to-head tournaments require RPS agents")
    rounds = min(
        inputs[0]["config"]["max_steps"],
        inputs[0]["config"].get("game_config", {}).get("horizon", 23),
    )
    seeds = list(range(seed, seed + episodes))
    pairs = []
    sums = [0.0] * len(models)
    played = [0] * len(models)
    total_pairs = len(models) * (len(models) - 1) // 2

    def observe(history):
        values = np.zeros(9, dtype=np.float32)
        for i, action in enumerate(history[:3]):
            values[3 * i + action] = 1
        return values

    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            trials = []
            for episode_seed in seeds:
                initial = np.random.default_rng(episode_seed).integers(0, 3, size=3).tolist()
                histories = [initial.copy(), initial.copy()]
                wins = losses = draws = 0
                for _ in range(rounds):
                    check()
                    left = models[i].act(observe(histories[1]), deterministic=True)
                    right = models[j].act(observe(histories[0]), deterministic=True)
                    if left == right:
                        draws += 1
                    elif (left - right) % 3 == 1:
                        wins += 1
                    else:
                        losses += 1
                    histories = [[left, *histories[0][:2]], [right, *histories[1][:2]]]
                trials.append(
                    {
                        "seed": episode_seed,
                        "initial_history": initial,
                        "wins": wins,
                        "losses": losses,
                        "draws": draws,
                        "net_wins": wins - losses,
                    }
                )
                sums[i] += wins - losses
                sums[j] += losses - wins
                played[i] += rounds
                played[j] += rounds
            pairs.append(
                {
                    "left": inputs[i]["experiment"],
                    "right": inputs[j]["experiment"],
                    "mean_net_wins": float(np.mean([t["net_wins"] for t in trials])),
                    "trials": trials,
                }
            )
            progress(len(pairs) / total_pairs)
    return {
        "protocol": "simultaneous RPS head-to-head",
        "seeds": seeds,
        "rounds_per_match": rounds,
        "pairs": pairs,
        "results": sorted(
            [
                {
                    "experiment": data["experiment"],
                    "mean_fitness": sums[i] / max(1, played[i]),
                    "std_fitness": None,
                    "environment_steps": played[i],
                    "fingerprint": data["fingerprint"],
                }
                for i, data in enumerate(inputs)
            ],
            key=lambda r: r["mean_fitness"],
            reverse=True,
        ),
        "note": "Fitness is net wins per throw against the other entrants. Both policies choose before either current move is revealed. Each seed supplies the same three-move starting history to both players; these are exploratory opponent matches.",
    }
