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

    @classmethod
    def get_asset_manifest(cls):
        return {
            "protocol": 1,
            "assets": {
                name: {"path": f"assets/{name}.svg", "media_type": "image/svg+xml"}
                for name in ("background", "player", "coin")
            },
        }

    def render_scene(self):
        from evoforge.rendering.builtin import sprite

        return {
            "protocol": 1,
            "width": 480,
            "height": 320,
            "nodes": [
                sprite("background", "background", 0, 0, 480, 320, layer=-1),
                sprite("player", "player", 70 + self.target * 220, 180, 64, 64),
                sprite("coin", "coin", 82 + self.target * 220, 100, 40, 40, animation="shine"),
                {
                    "id": "score",
                    "kind": "text",
                    "text": f"{self.score} CORRECT · {self.step_count}/{self.horizon}",
                    "x": 24,
                    "y": 24,
                    "hud": True,
                },
                {
                    "id": "target",
                    "kind": "text",
                    "text": f"NEXT TARGET: {self.target}",
                    "x": 24,
                    "y": 60,
                    "font_size": 16,
                    "color": "#bdd9c7",
                    "hud": True,
                },
            ],
            "animations": {"shine": {"frames": ["coin"], "fps": 4}},
        }
