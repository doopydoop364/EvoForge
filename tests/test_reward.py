from evoforge.algorithms import fitness_score
from evoforge.snake import Snake


def test_food_dominates_exploration():
    assert fitness_score(1, {(0, 0)}, 10) > fitness_score(
        0, {(x, y) for x in range(10) for y in range(10)}, 10
    )


def test_fitness_ignores_time_and_caps_exploration():
    visited = {(0, 0), (1, 0)}
    assert fitness_score(0, visited, 10) == fitness_score(0, visited, 10)
    assert fitness_score(0, visited, 10) < 0.01


def test_snake_tracks_unique_positions():
    env = Snake(size=8, max_steps=30)
    env.reset(42)
    assert len(env.visited) == 1
    env.step(1)
    assert len(env.visited) == 2
