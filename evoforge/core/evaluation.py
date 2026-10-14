"""Non-learning baselines, evaluated separately from training/validation."""

import numpy as np

from evoforge.games import close_env, environment_fitness, make_env, transition


def baseline(game, seeds, size=10, max_steps=300, game_config=None, heuristic=False):
    env = make_env(game, size, max_steps, game_config)
    scores, steps = [], 0
    try:
        for seed in seeds:
            rng = np.random.default_rng(seed)
            obs = env.reset(int(seed))
            done = False
            while not done:
                if heuristic and game == "snake":
                    safe = [a for a in (1, 0, 2) if obs[a] == 0]
                    action = safe[0] if safe else 1
                elif heuristic and game == "flappy":
                    action = 1 if env.y > env.gap else 0
                else:
                    action = int(rng.integers(env.action_size))
                obs, _, terminated, truncated, _ = transition(env, action)
                steps += 1
                done = terminated or truncated
            scores.append(environment_fitness(env))
    finally:
        close_env(env)
    return {
        "split": "test",
        "baseline": "heuristic" if heuristic else "random",
        "fitness": float(np.mean(scores)),
        "environment_steps": steps,
        "seeds": list(seeds),
    }
