"""Game-independent evolution operators and discrete actor-critic PPO."""

import numpy as np
import torch
from torch.distributions import Categorical

from .games import close_env, environment_fitness, make_env, metric, transition


@torch.no_grad()
def mutate(parent, rng, probability=0.05, sigma=0.08):
    child = parent.clone()
    for tensor in child.parameters():
        mask = torch.from_numpy((rng.random(tuple(tensor.shape)) < probability).astype(np.float32))
        noise = torch.from_numpy(rng.normal(0, sigma, tuple(tensor.shape)).astype(np.float32))
        tensor.add_(mask * noise)
    return child


@torch.no_grad()
def crossover(a, b, rng):
    if a.architecture != b.architecture:
        raise ValueError("Cannot cross incompatible policy architectures")
    child = a.clone()
    for dest, source in zip(child.parameters(), b.parameters()):
        mask = torch.from_numpy(rng.random(tuple(dest.shape)) < 0.5)
        dest.copy_(torch.where(mask, dest, source))
    return child


def fitness_score(food, visited, size):
    """Legacy built-in fitness: food dominates bounded exploration."""
    return float(food) + 0.01 * min(len(visited), size * size) / (size * size)


@torch.no_grad()
def evaluate_details(
    policy,
    seeds,
    size=10,
    max_steps=500,
    deterministic=True,
    game="snake",
    game_config=None,
    on_step=None,
):
    scores, outcomes, rewards = [], [], []
    steps = 0
    env = make_env(game, size, max_steps, game_config)
    try:
        for episode, seed in enumerate(seeds):
            obs = env.reset(seed=int(seed))
            env.episode_seed = int(seed)
            done, total_reward = False, 0.0
            while not done:
                obs, reward, terminated, truncated, info = transition(
                    env, policy.act(obs, deterministic=deterministic)
                )
                steps += 1
                total_reward += reward
                done = terminated or truncated
                if on_step:
                    on_step(env, episode, reward, terminated, truncated)
            scores.append(environment_fitness(env))
            outcomes.append(metric(env))
            rewards.append(total_reward)
    finally:
        close_env(env)
    return {
        "fitness": float(np.mean(scores)),
        "score": float(np.mean(outcomes)),
        "reward": float(np.mean(rewards)),
        "steps": steps,
    }


def evaluate(
    policy,
    seeds,
    size=10,
    max_steps=500,
    deterministic=True,
    game="snake",
    game_config=None,
    on_step=None,
):
    return evaluate_details(
        policy, seeds, size, max_steps, deterministic, game, game_config, on_step
    )["fitness"]


def ppo_refine(
    policy,
    seed,
    episodes=4,
    size=10,
    max_steps=500,
    epochs=3,
    lr=3e-4,
    gamma=0.99,
    gae_lambda=0.95,
    clip=0.2,
    game="snake",
    game_config=None,
    optimizer_state=None,
    on_step=None,
):
    """Complete on-policy episodes, terminal-aware GAE, timeout bootstrapping.

    Optimizer state and measured costs attach to returned model. Source is immutable.
    Local torch sampling generator makes calls reproducible without global RNG use.
    """
    model = policy.clone()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    if optimizer_state:
        optimizer.load_state_dict(optimizer_state)
    env = make_env(game, size, max_steps, game_config)
    rng = np.random.default_rng(seed)
    generator = torch.Generator().manual_seed(int(seed))
    observations, actions, old_logps, returns, advantages = [], [], [], [], []
    try:
        for episode in range(episodes):
            obs = env.reset(int(rng.integers(0, 2**31)))
            ep_obs, ep_act, ep_logp, ep_val, ep_rewards = [], [], [], [], []
            done = False
            while not done:
                with torch.no_grad():
                    logits, value = model(torch.as_tensor(obs, dtype=torch.float32).reshape(1, -1))
                    dist = Categorical(logits=logits)
                    action = torch.multinomial(dist.probs, 1, generator=generator).squeeze(-1)
                    logp = dist.log_prob(action)
                next_obs, reward, terminated, truncated, _ = transition(env, int(action.item()))
                ep_obs.append(obs)
                ep_act.append(int(action.item()))
                ep_logp.append(float(logp.item()))
                ep_val.append(float(value.item()))
                ep_rewards.append(reward)
                obs = next_obs
                done = terminated or truncated
                if on_step:
                    on_step(env, episode, reward, terminated, truncated)
            with torch.no_grad():
                bootstrap = (
                    0.0
                    if terminated
                    else float(
                        model(torch.as_tensor(obs, dtype=torch.float32).reshape(1, -1))[1].item()
                    )
                )
            gae, ep_adv = 0.0, []
            for t in reversed(range(len(ep_rewards))):
                next_v = ep_val[t + 1] if t + 1 < len(ep_rewards) else bootstrap
                delta = ep_rewards[t] + gamma * next_v - ep_val[t]
                gae = delta + gamma * gae_lambda * gae
                ep_adv.append(gae)
            ep_adv.reverse()
            observations.extend(ep_obs)
            actions.extend(ep_act)
            old_logps.extend(ep_logp)
            advantages.extend(ep_adv)
            returns.extend([a + v for a, v in zip(ep_adv, ep_val)])
    finally:
        close_env(env)
    x = torch.as_tensor(np.asarray(observations), dtype=torch.float32)
    a = torch.tensor(actions, dtype=torch.long)
    log_old = torch.tensor(old_logps, dtype=torch.float32)
    adv = torch.tensor(advantages, dtype=torch.float32)
    ret = torch.tensor(returns, dtype=torch.float32)
    adv = (adv - adv.mean()) / (adv.std(unbiased=False) + 1e-8)
    for _ in range(epochs):
        logits, values = model(x)
        dist = Categorical(logits=logits)
        ratio = torch.exp(dist.log_prob(a) - log_old)
        surrogate = torch.minimum(ratio * adv, torch.clamp(ratio, 1 - clip, 1 + clip) * adv)
        loss = -surrogate.mean() + 0.5 * ((values - ret) ** 2).mean() - 0.01 * dist.entropy().mean()
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
        optimizer.step()
    model.optimizer_state = optimizer.state_dict()
    model.training_stats = {
        "steps": len(actions),
        "loss": float(loss.detach()),
        "epochs": epochs,
        "entropy": float(dist.entropy().mean().detach()),
    }
    return model


@torch.no_grad()
def food_stats(policy, seeds, size=10, max_steps=500, game="snake", game_config=None):
    """Legacy name for raw outcome score, not fitness."""
    return evaluate_details(policy, seeds, size, max_steps, game=game, game_config=game_config)[
        "score"
    ]
