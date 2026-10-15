"""Presentation adapters for the unchanged built-in simulations."""

import time


def manifest(game):
    names = {
        "snake": ["board", "tile", "head", "body", "food"],
        "flappy": ["sky", "bird", "pipe", "ground"],
    }[game]
    return {
        "protocol": 1,
        "assets": {name: {"path": f"{name}.svg", "media_type": "image/svg+xml"} for name in names},
    }


def sprite(id, asset, x, y, width=32, height=32, **kwargs):
    return {
        "id": id,
        "kind": "sprite",
        "asset": asset,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        **kwargs,
    }


def scene(env, game):
    unit = 32
    width = env.size * unit
    nodes = []
    if game == "snake":
        nodes.append(sprite("board", "board", 0, 0, width, width, layer=-2))
        nodes.append(
            {
                "id": "grid",
                "kind": "tilemap",
                "columns": env.size,
                "tiles": [0] * (env.size**2),
                "palette": ["tile"],
                "layer": -1,
            }
        )
        nodes.extend(
            sprite(f"segment-{i}", "head" if i == 0 else "body", x * unit, y * unit)
            for i, (x, y) in enumerate(env.body)
        )
        if env.food:
            nodes.append(sprite("food", "food", env.food[0] * unit, env.food[1] * unit))
        score = env.food_eaten
    else:
        nodes.append(sprite("sky", "sky", 0, 0, width, width, layer=-2))
        for y in range(env.size):
            if abs(y - env.gap) > 1:
                nodes.append(sprite(f"pipe-{y}", "pipe", env.pipe_x * unit, y * unit))
        nodes.append(sprite("player", "bird", env.x * unit, env.y * unit))
        nodes.append(sprite("ground", "ground", 0, width - 6, width, 6, layer=2))
        score = env.score
    nodes.append(
        {
            "id": "score",
            "kind": "text",
            "x": 12,
            "y": 10,
            "text": f"{score} {'APPLES' if game == 'snake' else 'PIPES'}",
            "color": "#f1f9de",
            "hud": True,
            "layer": 10,
        }
    )
    return {
        "protocol": 1,
        "width": width,
        "height": width,
        "timestamp": time.time(),
        "nodes": nodes,
    }
