"""Public game contract. Plugins are explicitly installed Python packages."""

from dataclasses import dataclass
from typing import Any

import numpy as np
from gymnasium import spaces


@dataclass(frozen=True)
class GameInfo:
    id: str
    name: str
    version: str = "1.0.0"
    score_name: str = "score"
    sdk_version: int = 1


class GamePlugin:
    """Implement reset -> (observation, info), step -> (obs, reward, terminated,
    truncated, info). Observations must be numeric Box arrays; actions Discrete.
    Constructor accepts **game_config. close() is always called by the engine.
    """

    info: GameInfo
    observation_space: spaces.Box
    action_space: spaces.Discrete

    def reset(self, seed=None, options=None):
        raise NotImplementedError

    def step(self, action):
        raise NotImplementedError

    def fitness(self, info: dict[str, Any], episode_reward: float) -> float:
        return float(info.get("score", episode_reward))

    def render(self) -> str:
        return ""

    def render_terminal(self) -> str:
        return self.render()

    def render_scene(self) -> dict | None:
        """Optional renderer-v1 scene; called only for sampled presentation."""
        return None

    @classmethod
    def get_asset_manifest(cls) -> dict:
        return {"protocol": 1, "assets": {}}

    def spectator_frame(self) -> dict:
        return {"text": self.render()}

    def close(self):
        pass


class FlattenAdapter:
    """Engine adapter; legacy consumers retain reset obs / four-tuple step."""

    def __init__(self, plugin, max_steps=300):
        self.plugin = plugin
        self.observation_size, self.action_size = dimensions(plugin)
        self.size = int(getattr(plugin, "size", 10))
        self.max_steps = max_steps
        self.done = False
        self.last_info = {}
        self.steps = 0
        self.episode_reward = 0.0

    def _observation(self, observation):
        array = np.asarray(observation)
        if array.shape != self.plugin.observation_space.shape:
            raise ValueError(
                f"Observation shape {array.shape} differs from declared {self.plugin.observation_space.shape}"
            )
        if not np.isfinite(array).all() or not self.plugin.observation_space.contains(array):
            raise ValueError("Observation is nonfinite or outside declared space")
        array = array.astype(np.float32)
        if not np.isfinite(array).all():
            raise ValueError("Observation cannot be represented as finite float32 values")
        return array.reshape(-1)

    def reset(self, seed=None):
        observation, info = self.plugin.reset(seed=seed)
        self.steps = 0
        self.done = False
        self.episode_reward = 0.0
        if not isinstance(info, dict):
            raise ValueError("reset must return a metrics dict")
        self.last_info = info
        self.score = float(info.get("score", 0))
        return self._observation(observation)

    def transition(self, action):
        if self.done:
            raise RuntimeError("reset after episode end")
        if not self.plugin.action_space.contains(action):
            raise ValueError("Action outside declared Discrete space")
        obs, reward, terminated, truncated, info = self.plugin.step(action)
        if (
            not isinstance(info, dict)
            or not isinstance(terminated, (bool, np.bool_))
            or not isinstance(truncated, (bool, np.bool_))
        ):
            raise ValueError("step requires boolean terminated/truncated and a metrics dict")
        reward = float(reward)
        if not np.isfinite(reward):
            raise ValueError("Reward must be finite")
        self.steps += 1
        truncated = bool(truncated or (self.steps >= self.max_steps and not terminated))
        self.done = bool(terminated or truncated)
        self.episode_reward += reward
        self.last_info = dict(info)
        self.score = float(info.get("score", self.episode_reward))
        return self._observation(obs), reward, bool(terminated), truncated, info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.transition(action)
        return obs, reward, terminated or truncated, info

    def fitness(self):
        value = float(self.plugin.fitness(self.last_info, self.episode_reward))
        if not np.isfinite(value):
            raise ValueError("Fitness must be finite")
        return value

    def render(self):
        return self.plugin.render()

    def spectator_frame(self):
        return self.plugin.spectator_frame()

    def close(self):
        self.plugin.close()


def dimensions(plugin):
    if not isinstance(plugin.observation_space, spaces.Box) or not plugin.observation_space.shape:
        raise ValueError("v1 requires a numeric Box observation space")
    if not np.issubdtype(plugin.observation_space.dtype, np.number):
        raise ValueError("Box observations must be numeric")
    if not isinstance(plugin.action_space, spaces.Discrete) or plugin.action_space.start != 0:
        raise ValueError("v1 requires a zero-based Discrete action space")
    return int(np.prod(plugin.observation_space.shape)), int(plugin.action_space.n)
