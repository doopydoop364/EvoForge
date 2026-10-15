"""Shared game contract and registry for EvoForge environments."""

from dataclasses import dataclass

from .flappy import Flappy
from .geometrydash import GeometryDash
from .snake import Snake


@dataclass(frozen=True)
class GameSpec:
    id: str
    title: str
    environment: type
    observation_size: int
    action_size: int
    score_label: str


GAMES = {
    "snake": GameSpec("snake", "Snake", Snake, 17, 3, "apples"),
    "flappy": GameSpec("flappy", "Flappy-style", Flappy, 17, 3, "pipes"),
    "geometrydash": GameSpec(
        "geometrydash", "Geometry Dash-style", GeometryDash, 17, 3, "tiles cleared"
    ),
}


def game_spec(game="snake"):
    if game not in GAMES:
        from .sdk.registry import create, discover

        plugins = discover()
        if game in plugins:
            env = create(game)
            try:
                info = plugins[game].info
                return GameSpec(
                    info.id,
                    info.name,
                    plugins[game],
                    env.observation_size,
                    env.action_size,
                    info.score_name,
                )
            finally:
                env.close()

    try:
        return GAMES[game]
    except KeyError as exc:
        raise ValueError(f"Unknown game {game!r}. Available: {', '.join(GAMES)}") from exc


def make_env(game="snake", size=10, max_steps=300, game_config=None):
    if game in GAMES:
        if game_config:
            raise ValueError("Built-in games use size/max_steps configuration")
        return game_spec(game).environment(size, max_steps)
    from .sdk.registry import create

    return create(game, game_config, max_steps)


def metric(env):
    return float(getattr(env, "score", getattr(env, "food_eaten", 0)))


def environment_fitness(env):
    if hasattr(env, "fitness"):
        return env.fitness()
    # Built-in legacy reward and fitness remain unchanged.
    from .algorithms import fitness_score

    return fitness_score(metric(env), getattr(env, "visited", set()), env.size)


def available_games():
    from .sdk.registry import discover

    return list(GAMES) + list(discover())


def game_version(game):
    if game in GAMES:
        return "0.9.0"
    from .sdk.registry import discover

    return discover()[game].info.version


def transition(env, action):
    """Normalize legacy built-ins and Gymnasium plugins to five-tuples."""
    if hasattr(env, "transition"):
        return env.transition(action)
    obs, reward, done, info = env.step(action)
    # Snake starvation is a game terminal condition; time limits are truncations.
    terminal = bool(
        done
        and (
            getattr(env, "food", True) is None
            or reward == -1.0
            or getattr(env, "steps_without_food", 0) >= max(env.size * 2, env.size * env.size // 2)
        )
    )
    truncated = bool(done and not terminal)
    return obs, reward, terminal, truncated, info


def frame(env):
    data = (
        env.spectator_frame()
        if hasattr(env, "spectator_frame")
        else {"text": env.render(), "score": metric(env), "steps": env.steps}
    )
    provider = getattr(env, "plugin", env)
    render = getattr(provider, "render_scene", None)
    if render:
        try:
            scene = render()
            if scene is not None:
                from .rendering.schema import validate_scene

                data["scene"] = validate_scene(scene)
        except (ValueError, TypeError) as exc:
            # A presentation error must not fail otherwise-valid simulation.
            data["render_error"] = str(exc)[:512]
    return data


def close_env(env):
    close = getattr(env, "close", None)
    if close:
        close()
