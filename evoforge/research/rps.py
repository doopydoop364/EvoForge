"""Small reproducible RPS benchmark with fixed opponents (no implicit coevolution)."""

import numpy as np
from gymnasium import spaces

from evoforge.sdk.game import GameInfo, GamePlugin


class RPS(GamePlugin):
    info = GameInfo("rps", "Rock Paper Scissors", "1.0.0", "net wins")
    observation_space = spaces.Box(0, 1, (9,), dtype=np.float32)
    action_space = spaces.Discrete(3)

    def __init__(self, opponent="cycle", horizon=23):
        if opponent not in {"cycle", "random", "repeat", "counter"}:
            raise ValueError("RPS opponent must be cycle, random, repeat or counter")
        if type(horizon) is not int or not 1 <= horizon <= 10000:
            raise ValueError("RPS horizon must be 1–10,000")
        self.opponent, self.horizon = opponent, horizon
        self.reset(0)

    def observation(self):
        obs = np.zeros(9, dtype=np.float32)
        for i, action in enumerate(self.history[:3]):
            obs[3 * i + action] = 1
        return obs

    def reset(self, seed=None, options=None):
        self.rng = np.random.default_rng(seed)
        self.offset = int(self.rng.integers(3))
        self.history, self.previous = [], self.offset
        self.steps = self.score = 0
        return self.observation(), {"score": 0}

    def step(self, action):
        if not self.action_space.contains(action) or self.steps >= self.horizon:
            raise ValueError("Invalid RPS action or completed episode")
        # Opponent chooses using only past state; neither player sees the current move.
        other = {
            "cycle": (self.offset + self.steps) % 3,
            "repeat": self.previous,
            "counter": (self.previous + 1) % 3,
        }.get(self.opponent)
        if self.opponent == "random":
            other = int(self.rng.integers(3))
        reward = 0 if action == other else 1 if (int(action) - other) % 3 == 1 else -1
        self.history.insert(0, other)
        self.history = self.history[:3]
        self.previous = int(action)
        self.steps += 1
        self.score += reward
        return (
            self.observation(),
            float(reward),
            self.steps >= self.horizon,
            False,
            {"score": self.score},
        )

    def render(self):
        names = ["rock", "paper", "scissors"]
        history = ", ".join(names[a] for a in self.history) or "no moves yet"
        return f"RPS · {self.opponent} opponent\nRound {self.steps}/{self.horizon} · Net wins {self.score}\nOpponent history (newest first): {history}"
