import numpy as np
import pytest
from gymnasium import spaces
from evoforge.sdk import GameInfo, GamePlugin, register, validate_game
from evoforge.sdk.registry import discover
from evoforge.games import make_env
from evoforge.agents import policy_for
from evoforge.algorithms import crossover


class WideGame(GamePlugin):
    info = GameInfo("wide-test", "Wide test")
    observation_space = spaces.Box(-1, 1, (3, 2), dtype=np.float32)
    action_space = spaces.Discrete(5)
    def reset(self, seed=None, options=None):
        return np.zeros((3, 2), dtype=np.float32), {}
    def step(self, action):
        return self.reset()[0], 1.0, True, False, {"score": 7}


def test_installed_example_discovered():
    assert "coin" in discover(refresh=True)
    assert validate_game("coin")["observation_size"] == 4


def test_dimensions_flatten_fitness_and_architecture():
    register(WideGame)
    env = make_env("wide-test")
    obs = env.reset(9)
    assert obs.shape == (6,)
    policy = policy_for("wide-test", hidden=[7, 4, 3])
    assert 0 <= policy.act(obs) < 5
    assert policy.clone().architecture == policy.architecture
    env.step(4)
    assert env.fitness() == 7
    with pytest.raises(ValueError, match="incompatible"):
        crossover(policy, policy_for("snake"), np.random.default_rng(1))


def test_invalid_plugins_have_readable_failures():
    class Bad(WideGame):
        info = GameInfo("bad-version", "Bad", sdk_version=99)
    with pytest.raises(ValueError, match="SDK version"):
        register(Bad)
    class BadSpace(WideGame):
        info = GameInfo("bad-space", "Bad Space")
        action_space = spaces.Box(-1, 1, (2,))
    register(BadSpace)
    with pytest.raises(ValueError, match="Discrete"):
        validate_game("bad-space")
    class BadReset(WideGame):
        info = GameInfo("bad-reset", "Bad Reset")
        def reset(self, seed=None, options=None):
            return np.ones((2, 3), dtype=np.float32), {}
    register(BadReset)
    with pytest.raises(ValueError, match="shape"):
        validate_game("bad-reset")
