import numpy as np
import pytest

from evoforge.algorithms import evaluate, ppo_refine
from evoforge.games import game_spec, make_env, metric
from evoforge.policy import Policy
from evoforge.trainer import Config, Trainer


@pytest.mark.parametrize("name", ["snake", "flappy"])
def test_shared_contract(name):
    spec = game_spec(name)
    env = make_env(name, 10, 80)
    obs = env.reset(8)
    assert obs.shape == (spec.observation_size,)
    assert spec.action_size == 3
    for _ in range(80):
        obs, reward, done, info = env.step(0)
        assert obs.shape == (17,)
        assert np.isfinite(reward)
        assert metric(env) >= 0
        if done:
            break
    assert done
    assert len(env.render().splitlines()) == 10


def test_flappy_repeatable():
    def episode():
        env = make_env("flappy", 10, 90)
        env.reset(123)
        events = []
        for a in [1, 0, 0, 1, 0, 2] * 15:
            obs, r, done, info = env.step(a)
            events.append((r, tuple(obs), done, info["score"]))
            if done:
                break
        return events

    assert episode() == episode()


def test_flappy_train_and_resume(tmp_path):
    cfg = Config(
        game="flappy",
        mode="evolution",
        population=4,
        elites=1,
        ppo_candidates=0,
        generations=1,
        eval_episodes=1,
        max_steps=25,
    )
    Trainer(cfg, tmp_path).run()
    assert (tmp_path / "champion.pt").exists()
    cfg.generations = 2
    Trainer(cfg, tmp_path, resume=True).run()
    assert (tmp_path / "spectator.pt").exists()


def test_flappy_ppo():
    model = Policy()
    candidate = ppo_refine(model, 99, episodes=1, size=10, max_steps=25, epochs=1, game="flappy")
    assert np.isfinite(evaluate(candidate, [1, 2], game="flappy", max_steps=25))
