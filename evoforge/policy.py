"""Fixed-topology actor-critic suitable for mutation and PPO."""
import torch
from torch import nn

class Policy(nn.Module):
    def __init__(self, input_size=17, hidden=64, actions=3):
        super().__init__()
        self.encoder=nn.Sequential(nn.Linear(input_size,hidden),nn.Tanh(),nn.Linear(hidden,hidden),nn.Tanh())
        self.actor=nn.Linear(hidden,actions)
        self.critic=nn.Linear(hidden,1)

    def forward(self, x):
        features=self.encoder(x)
        return self.actor(features),self.critic(features).squeeze(-1)

    @torch.no_grad()
    def act(self, obs, deterministic=False, generator=None):
        logits,_=self(torch.as_tensor(obs,dtype=torch.float32).unsqueeze(0))
        if deterministic:
            return int(logits.argmax(dim=-1).item())
        probs=torch.softmax(logits.squeeze(0),dim=-1)
        return int(torch.multinomial(probs,1,generator=generator).item())

    def clone(self):
        other=Policy(self.encoder[0].in_features,self.encoder[0].out_features,self.actor.out_features)
        other.load_state_dict(self.state_dict())
        return other
