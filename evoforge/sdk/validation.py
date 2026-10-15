"""Executable validation for explicitly installed, trusted plugins."""

import json

import numpy as np


def validate_game(game, config=None, max_steps=64):
    from evoforge.games import environment_fitness, frame, make_env, transition

    env = make_env(game, max_steps=max_steps, game_config=config)
    try:
        first = env.reset(123)
        second = env.reset(123)
        if not np.array_equal(first, second):
            raise ValueError("reset(seed=123) is not deterministic")

        def episode():
            env.reset(123)
            trace = []
            for step in range(max_steps):
                obs, reward, terminated, truncated, info = transition(env, step % env.action_size)
                if not np.isfinite(obs).all() or not np.isfinite(reward):
                    raise ValueError("Observations and rewards must be finite")
                payload = frame(env)
                if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
                    raise ValueError("spectator_frame must return a dict with terminal text")
                if len(json.dumps(payload, allow_nan=False).encode()) > 65536:
                    raise ValueError("spectator frame exceeds 64 KiB")
                json.dumps(info, allow_nan=False)
                trace.append((obs.tolist(), reward, terminated, truncated, info))
                if terminated or truncated:
                    break
            if not np.isfinite(environment_fitness(env)):
                raise ValueError("Fitness must be finite")
            return trace

        if episode() != episode():
            raise ValueError("Seeded action trajectory is not deterministic")
        if not isinstance(env.render(), str):
            raise ValueError("render() must return terminal text")
        return {
            "game": game,
            "valid": True,
            "observation_size": len(first),
            "action_size": env.action_size,
        }
    finally:
        close = getattr(env, "close", None)
        if close:
            close()
