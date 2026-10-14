"""Independent champion/population replay; never advances the training worker."""

from evoforge.agents import policy_for
from evoforge.agents.serialization import load_policy
from evoforge.core.checkpoints import safe_load
from evoforge.games import close_env, frame, make_env, transition


class Replay:
    def __init__(self, directory, mode="champion", seed=900, limit=9):
        if mode not in ("champion", "population"):
            raise ValueError("Replay mode must be champion or population")
        from pathlib import Path

        directory = Path(directory)
        self.mode, self.seed, self.agents = mode, seed, []
        if mode == "champion":
            policy, cfg = load_policy(directory / "champion.pt")
            policies = [policy]
        else:
            data = safe_load(directory / "spectator.pt")
            cfg, policies = data["config"], []
            for state in data["policies"][:limit]:
                policy = policy_for(
                    cfg.get("game", "snake"),
                    cfg["hidden"],
                    cfg.get("game_config"),
                    cfg["size"],
                    cfg["max_steps"],
                )
                policy.load_state_dict(state)
                policies.append(policy)
        try:
            for i, policy in enumerate(policies):
                env = make_env(
                    cfg.get("game", "snake"), cfg["size"], cfg["max_steps"], cfg.get("game_config")
                )
                self.agents.append(
                    {"env": env, "policy": policy, "obs": env.reset(seed + i), "seed": seed + i}
                )
        except Exception:
            self.close()
            raise

    def tick(self):
        frames = []
        for i, agent in enumerate(self.agents):
            env = agent["env"]
            if env.done:
                agent["seed"] += 101
                agent["obs"] = env.reset(agent["seed"])
            obs, reward, terminated, truncated, info = transition(
                env, agent["policy"].act(agent["obs"], deterministic=True)
            )
            agent["obs"] = obs
            frames.append(
                {
                    "agent": str(i),
                    "mode": self.mode,
                    "data": frame(env),
                    "reward": reward,
                    "terminated": terminated,
                    "truncated": truncated,
                    "metrics": info,
                }
            )
        return frames

    def close(self):
        for agent in self.agents:
            close_env(agent["env"])
