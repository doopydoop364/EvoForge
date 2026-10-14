"""Configurable CPU actor-critic; legacy two-layer state keys stay compatible."""
import torch
from torch import nn


class Policy(nn.Module):
    def __init__(self, input_size=17, hidden=64, actions=3):
        super().__init__()
        widths = [hidden, hidden] if isinstance(hidden, int) else list(hidden)
        if not widths or any(not isinstance(n, int) or n < 1 for n in [input_size, actions, *widths]):
            raise ValueError("Policy dimensions and hidden widths must be positive integers")
        self.architecture = {"input_size": input_size, "hidden": widths, "actions": actions}
        layers = []
        previous = input_size
        for width in widths:
            layers.extend([nn.Linear(previous, width), nn.Tanh()])
            previous = width
        self.encoder = nn.Sequential(*layers)
        self.actor = nn.Linear(previous, actions)
        self.critic = nn.Linear(previous, 1)

    def forward(self, x):
        features = self.encoder(x)
        return self.actor(features), self.critic(features).squeeze(-1)

    @torch.no_grad()
    def act(self, obs, deterministic=False, generator=None):
        logits, _ = self(torch.as_tensor(obs, dtype=torch.float32).reshape(1, -1))
        if deterministic:
            return int(logits.argmax(dim=-1).item())
        return int(torch.multinomial(torch.softmax(logits.squeeze(0), dim=-1), 1, generator=generator).item())

    def clone(self):
        other = Policy(**self.architecture)
        other.load_state_dict(self.state_dict())
        return other
