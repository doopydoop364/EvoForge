"""Deterministic Flappy-style grid environment with the shared game API.

This is a new simple benchmark, not an emulation of commercial Flappy Bird.
Actions: 0 = coast, 1 = flap, 2 = dive. 17 observations, 3 actions.
"""
import numpy as np

class Flappy:
    observation_size = 17
    action_size = 3
    score_label = "pipes"
    def __init__(self, size=10, max_steps=300):
        if size < 7: raise ValueError("Flappy size must be >=7")
        self.size, self.max_steps = size, max_steps
        self.reset()

    def reset(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.steps = self.score = self.food_eaten = self.steps_without_food = 0
        self.done = False
        self.x = 2
        self.y = self.size // 2
        self.velocity = 0
        self.gap = self._gap()
        self.pipe_x = self.size - 1
        self.visited = {(self.x, self.y)}
        return self.observe()

    def _gap(self):
        return int(self.rng.integers(2, self.size-2))

    def observe(self):
        return np.array([
            self.y/(self.size-1), self.velocity/2,
            (self.pipe_x-self.x)/(self.size-1), self.gap/(self.size-1),
            (self.gap-self.y)/(self.size-1), float(self.y<=1),float(self.y>=self.size-2),
            float(self.pipe_x==self.x+1),float(self.pipe_x==self.x),
            float(self.y < self.gap-1), float(self.y > self.gap+1),
            self.score / max(1,self.size), self.steps/self.max_steps,
            1.0,0.0,0.0,0.0], dtype=np.float32)

    def step(self, action):
        if self.done: raise RuntimeError("reset after terminal state")
        if int(action) not in (0,1,2): raise ValueError("action must be 0,1,2")
        self.steps += 1
        # Discrete momentum; allows intentional altitude changes.
        self.velocity = -1 if action == 1 else 1 if action == 2 else max(-1,min(1,self.velocity+1))
        self.y += self.velocity
        self.pipe_x -= 1
        collided = self.y < 0 or self.y >= self.size
        if self.pipe_x == self.x and abs(self.y-self.gap)>1: collided = True
        reward = -1.0 if collided else -0.001
        if not collided and self.pipe_x < self.x:
            self.score += 1
            self.food_eaten = self.score
            reward += 2.0
            self.pipe_x = self.size-1
            self.gap = self._gap()
        self.done = collided or self.steps >= self.max_steps
        if not collided: self.visited.add((self.x,self.y))
        return self.observe(),reward,self.done,{"food":self.score,"score":self.score,"steps":self.steps}

    def render(self):
        lines=[]
        for y in range(self.size):
            line=[]
            for x in range(self.size):
                if (x,y)==(self.x,self.y): ch='H'
                elif x==self.pipe_x and abs(y-self.gap)>1: ch='#'
                elif x==self.pipe_x: ch=' '
                else: ch='.'
                line.append(ch)
            lines.append(''.join(line))
        return '\n'.join(lines)
