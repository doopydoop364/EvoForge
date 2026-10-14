"""Shared game contract and registry for EvoForge environments."""
from dataclasses import dataclass
from .snake import Snake
from .flappy import Flappy

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
}

def game_spec(game="snake"):
    try:
        return GAMES[game]
    except KeyError as exc:
        raise ValueError(f"Unknown game {game!r}. Available: {', '.join(GAMES)}") from exc

def make_env(game="snake", size=10, max_steps=300):
    return game_spec(game).environment(size, max_steps)

def metric(env):
    return int(getattr(env, "score", getattr(env, "food_eaten", 0)))

def environment_fitness(env):
    # Only bounded tie-breaking reward; never reward indefinite survival.
    from .algorithms import fitness_score
    return fitness_score(metric(env), getattr(env, "visited", set()), env.size)
