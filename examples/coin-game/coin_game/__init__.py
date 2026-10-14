"""Two actions, a 2x2 numeric observation, reward distinct from score fitness."""

import numpy as np
from gymnasium import spaces

from evoforge.sdk import GameInfo, GamePlugin


class CoinGame(GamePlugin):
    info = GameInfo("coin", "Coin prediction", score_name="correct predictions")
    observation_space = spaces.Box(0, 1, shape=(2, 2), dtype=np.float32)
    action_space = spaces.Discrete(2)

    def __init__(self, horizon=12):
        if not isinstance(horizon, int) or not 1 <= horizon <= 10000:
            raise ValueError("horizon must be an integer between 1 and 10000")
        self.horizon = horizon

    def _observe(self):
        return np.array(
            [[self.target, 1 - self.target], [self.step_count / self.horizon, 1]], dtype=np.float32
        )

    def reset(self, seed=None, options=None):
        self.rng = np.random.default_rng(seed)
        self.target = int(self.rng.integers(2))
        self.score = self.step_count = 0
        return self._observe(), {"score": 0}

    def step(self, action):
        if not self.action_space.contains(action):
            raise ValueError("action must be 0 or 1")
        correct = int(action == self.target)
        self.score += correct
        self.step_count += 1
        self.target = int(self.rng.integers(2))
        return (
            self._observe(),
            float(2 * correct - 1),
            False,
            self.step_count >= self.horizon,
            {"score": self.score},
        )

    def render(self):
        return f"Coin: {self.target} | Score: {self.score} | Step: {self.step_count}/{self.horizon}"
