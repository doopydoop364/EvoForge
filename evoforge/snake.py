"""Deterministic, headless Snake environment with a Gym-like interface."""

from collections import deque

import numpy as np

DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))


class Snake:
    observation_size = 17
    action_size = 3  # left, straight, right

    def __init__(self, size=10, max_steps=500):
        if size < 5:
            raise ValueError("size must be >=5")
        self.size, self.max_steps = size, max_steps
        self.reset()

    def reset(self, seed=None):
        self.rng = np.random.default_rng(seed)
        c = self.size // 2
        self.body = deque([(c, c), (c - 1, c), (c - 2, c)])
        self.direction = 1
        self.steps = self.food_eaten = self.steps_without_food = 0
        self.done = False
        self.visited = {self.body[0]}
        self._place_food()
        return self.observe()

    def _place_food(self):
        free = [
            (x, y) for y in range(self.size) for x in range(self.size) if (x, y) not in self.body
        ]
        self.food = free[int(self.rng.integers(len(free)))] if free else None

    def _danger(self, direction):
        dx, dy = DIRECTIONS[direction % 4]
        x, y = self.body[0]
        nxt = (x + dx, y + dy)
        # Stepping into the tail is legal when the tail will move away.
        return float(
            not (0 <= nxt[0] < self.size and 0 <= nxt[1] < self.size) or nxt in list(self.body)[:-1]
        )

    def _ray_distance(self, direction):
        dx, dy = DIRECTIONS[direction % 4]
        x, y = self.body[0]
        distance = 0
        occupied = set(list(self.body)[:-1])
        while True:
            x += dx
            y += dy
            if not (0 <= x < self.size and 0 <= y < self.size) or (x, y) in occupied:
                break
            distance += 1
        return distance / (self.size - 1)

    def observe(self):
        x, y = self.body[0]
        fx, fy = self.food if self.food is not None else (x, y)
        d = self.direction
        return np.asarray(
            [
                self._danger(d - 1),
                self._danger(d),
                self._danger(d + 1),
                float(d == 0),
                float(d == 1),
                float(d == 2),
                float(d == 3),
                (fx - x) / (self.size - 1),
                (fy - y) / (self.size - 1),
                x / (self.size - 1),
                y / (self.size - 1),
                self._ray_distance(d - 1),
                self._ray_distance(d),
                self._ray_distance(d + 1),
                float(fx < x),
                float(fx > x),
                float(fy < y),
            ],
            dtype=np.float32,
        )

    def step(self, action):
        if self.done:
            raise RuntimeError("reset after terminal state")
        action = int(action)
        if action not in (0, 1, 2):
            raise ValueError("action must be 0,1,2")
        self.direction = (self.direction + action - 1) % 4
        dx, dy = DIRECTIONS[self.direction]
        x, y = self.body[0]
        nxt = (x + dx, y + dy)
        self.steps += 1
        self.steps_without_food += 1
        ate = nxt == self.food
        wall = not (0 <= nxt[0] < self.size and 0 <= nxt[1] < self.size)
        collision = nxt in (self.body if ate else list(self.body)[:-1])
        if wall or collision:
            self.done = True
            return self.observe(), -1.0, True, {"food": self.food_eaten, "steps": self.steps}
        self.body.appendleft(nxt)
        self.visited.add(nxt)
        if ate:
            self.food_eaten += 1
            self.steps_without_food = 0
            self._place_food()
        else:
            self.body.pop()
        # Starvation limits stalling without offering a survival-based fitness reward.
        starvation_limit = max(self.size * 2, self.size * self.size // 2)
        self.done = (
            self.food is None
            or self.steps >= self.max_steps
            or self.steps_without_food >= starvation_limit
        )
        # Sparse food objective: avoid an endlessly farmable distance-shaping reward.
        # The next food is a new objective immediately after a successful meal.
        reward = (2.0 if ate else -0.002) + (3.0 if self.food is None else 0.0)
        return self.observe(), reward, self.done, {"food": self.food_eaten, "steps": self.steps}

    def render_scene(self):
        from .rendering.builtin import scene

        return scene(self, "snake")

    def render_terminal(self):
        return self.render()

    @classmethod
    def get_asset_manifest(cls):
        from .rendering.builtin import manifest

        return manifest("snake")

    def render(self):
        occupied = set(self.body)
        return "\n".join(
            "".join(
                "H"
                if (x, y) == self.body[0]
                else "o"
                if (x, y) in occupied
                else "*"
                if (x, y) == self.food
                else "."
                for x in range(self.size)
            )
            for y in range(self.size)
        )
