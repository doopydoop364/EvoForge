from evoforge.games import make_env
from evoforge.policy import Policy


def policy_for(game="snake", hidden=64, game_config=None, size=10, max_steps=300):
    env = make_env(game, size, max_steps, game_config=game_config)
    try:
        return Policy(input_size=env.observation_size, hidden=hidden, actions=env.action_size)
    finally:
        close = getattr(env, "close", None)
        if close:
            close()
