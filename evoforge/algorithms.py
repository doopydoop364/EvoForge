"""Evolution operators and a compact on-policy PPO learner."""
import numpy as np
import torch
from torch.distributions import Categorical
from .policy import Policy
from .games import make_env, environment_fitness, metric

@torch.no_grad()
def mutate(parent, rng, probability=0.05, sigma=0.08):
    child=parent.clone()
    for tensor in child.parameters():
        mask=torch.from_numpy((rng.random(tuple(tensor.shape))<probability).astype(np.float32))
        noise=torch.from_numpy(rng.normal(0,sigma,tuple(tensor.shape)).astype(np.float32))
        tensor.add_(mask*noise)
    return child

@torch.no_grad()
def crossover(a,b,rng):
    child=a.clone()
    for dest,source in zip(child.parameters(),b.parameters()):
        mask=torch.from_numpy(rng.random(tuple(dest.shape))<0.5)
        dest.copy_(torch.where(mask,dest,source))
    return child

def fitness_score(food, visited, size):
    """Food dominates; bounded exploration is only a tie-breaker (never time-based)."""
    return float(food) + 0.01 * min(len(visited), size * size) / (size * size)


def evaluate(policy, seeds, size=10, max_steps=500, deterministic=True, game="snake"):
    scores=[]
    for seed in seeds:
        env=make_env(game,size,max_steps)
        obs=env.reset(seed=int(seed))
        terminated=False
        while not terminated:
            obs,_,terminated,info=env.step(policy.act(obs,deterministic=deterministic))
        scores.append(environment_fitness(env))
    return float(np.mean(scores))

def ppo_refine(policy, seed, episodes=4, size=10, max_steps=500, epochs=3, lr=3e-4,
               gamma=0.99, gae_lambda=0.95, clip=0.2, game="snake"):
    """Train on complete episodes, computing terminal-aware generalized advantages.

    Returns a new model; the source genome is never changed.
    """
    model=policy.clone()
    optimizer=torch.optim.Adam(model.parameters(),lr=lr)
    env=make_env(game,size,max_steps)
    rng=np.random.default_rng(seed)
    observations,actions,old_logps,returns,advantages=[],[],[],[],[]
    for _ in range(episodes):
        obs=env.reset(int(rng.integers(0,2**31)))
        ep_obs,ep_act,ep_logp,ep_val,ep_rewards=[],[],[],[],[]
        done=False
        while not done:
            with torch.no_grad():
                logits,value=model(torch.as_tensor(obs,dtype=torch.float32).unsqueeze(0))
                dist=Categorical(logits=logits)
                action=dist.sample()
                logp=dist.log_prob(action)
            next_obs,reward,done,_=env.step(int(action.item()))
            ep_obs.append(obs);ep_act.append(int(action.item()))
            ep_logp.append(float(logp.item()));ep_val.append(float(value.item()))
            ep_rewards.append(reward)
            obs=next_obs
        gae=0.0
        ep_adv=[]
        for t in reversed(range(len(ep_rewards))):
            next_v=ep_val[t+1] if t+1<len(ep_rewards) else 0.0
            delta=ep_rewards[t]+gamma*next_v-ep_val[t]
            gae=delta+gamma*gae_lambda*gae
            ep_adv.append(gae)
        ep_adv.reverse()
        observations.extend(ep_obs);actions.extend(ep_act);old_logps.extend(ep_logp)
        advantages.extend(ep_adv)
        returns.extend([a+v for a,v in zip(ep_adv,ep_val)])
    x=torch.as_tensor(np.asarray(observations),dtype=torch.float32)
    a=torch.tensor(actions,dtype=torch.long)
    log_old=torch.tensor(old_logps,dtype=torch.float32)
    adv=torch.tensor(advantages,dtype=torch.float32)
    ret=torch.tensor(returns,dtype=torch.float32)
    adv=(adv-adv.mean())/(adv.std(unbiased=False)+1e-8)
    for _ in range(epochs):
        logits,values=model(x)
        dist=Categorical(logits=logits)
        ratio=torch.exp(dist.log_prob(a)-log_old)
        surrogate=torch.minimum(ratio*adv,torch.clamp(ratio,1-clip,1+clip)*adv)
        loss=-surrogate.mean()+0.5*((values-ret)**2).mean()-0.01*dist.entropy().mean()
        optimizer.zero_grad();loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),0.5)
        optimizer.step()
    return model


@torch.no_grad()
def food_stats(policy, seeds, size=10, max_steps=500, game="snake"):
    """Mean apples eaten; unlike fitness this contains no shaping or exploration bonus."""
    apples=[]
    for seed in seeds:
        env=make_env(game,size,max_steps)
        obs=env.reset(int(seed))
        done=False
        while not done:
            obs,_,done,info=env.step(policy.act(obs,deterministic=True))
        apples.append(metric(env))
    return float(np.mean(apples))
