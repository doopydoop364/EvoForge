"""Presentation adapters for the unchanged built-in simulations."""

import time


def manifest(game):
    if game == "geometrydash":
        # This simulator provides terminal frames. A missing graphical layer is
        # a supported capability, not a missing-asset error.
        return {"protocol": 1, "assets": {}}
    if game == "snake":
        paths = {
            "board": "board.svg",
            "tile": "tile.svg",
            "head": "nokia-headr.png",
            "body": "nokia-bodyr.png",
            "food": "nokia-nibble.png",
        }
        for part in ("head", "body", "tail"):
            for direction, suffix in zip(("up", "down", "left", "right"), "udlr"):
                paths[f"{part}-{direction}"] = f"nokia-{part}{suffix}.png"
        paths.update({f"turn-{i}": f"nokia-turn{i}.png" for i in range(4)})
    elif game == "flappy":
        paths = {
            "sky": "flappy-background-day.png",
            "bird": "flappy-yellowbird-midflap.png",
            "bird-up": "flappy-yellowbird-upflap.png",
            "bird-down": "flappy-yellowbird-downflap.png",
            "pipe": "flappy-pipe-green.png",
            "ground": "flappy-base.png",
        }
    else:
        raise KeyError(game)
    return {
        "protocol": 1,
        "assets": {
            name: {
                "path": path,
                "media_type": "image/png" if path.endswith(".png") else "image/svg+xml",
                "scale_mode": "nearest",
            }
            for name, path in paths.items()
        },
    }


def snake_segment_asset(body, index, direction):
    """Select the supplied Nokia sprite from actual adjacent segment positions."""
    names = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}
    if index == 0:
        return f"head-{('up', 'right', 'down', 'left')[direction]}"
    x, y = body[index]
    front = (body[index - 1][0] - x, body[index - 1][1] - y)
    if index == len(body) - 1:
        return f"tail-{names[front]}"
    back = (body[index + 1][0] - x, body[index + 1][1] - y)
    corners = {
        frozenset(((0, 1), (1, 0))): 0,
        frozenset(((0, 1), (-1, 0))): 1,
        frozenset(((0, -1), (-1, 0))): 2,
        frozenset(((0, -1), (1, 0))): 3,
    }
    corner = corners.get(frozenset((front, back)))
    return f"turn-{corner}" if corner is not None else f"body-{names[front]}"


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
    animations = {}
    if game == "snake":
        top = 36
        height = width + top
        nodes.append(sprite("board", "board", 0, 0, width, height, layer=-2))
        nodes.append(
            {
                "id": "grid",
                "kind": "tilemap",
                "y": top,
                "columns": env.size,
                "tiles": [0] * (env.size**2),
                "palette": ["tile"],
                "layer": -1,
            }
        )
        body = list(env.body)
        nodes.extend(
            sprite(
                f"segment-{i}",
                snake_segment_asset(body, i, env.direction),
                x * unit,
                y * unit + top,
            )
            for i, (x, y) in enumerate(body)
        )
        if env.food:
            nodes.append(sprite("food", "food", env.food[0] * unit, env.food[1] * unit + top))
        score = env.food_eaten
    else:
        ground_height = round(width * 112 / 336)
        height = width + ground_height
        sky_height = width * 512 / 288
        nodes.append(sprite("sky", "sky", 0, width - sky_height, width, sky_height, layer=-2))
        upper_height = max(0, env.gap - 1) * unit
        lower_y = min(env.size, env.gap + 2) * unit
        if upper_height:
            nodes.append(
                sprite(
                    "pipe-upper",
                    "pipe",
                    env.pipe_x * unit,
                    upper_height,
                    unit,
                    upper_height,
                    scale_y=-1,
                )
            )
        if lower_y < width:
            nodes.append(
                sprite("pipe-lower", "pipe", env.pipe_x * unit, lower_y, unit, width - lower_y)
            )
        bird_height = unit * 24 / 34
        nodes.append(
            sprite(
                "player",
                "bird",
                env.x * unit,
                env.y * unit + (unit - bird_height) / 2,
                unit,
                bird_height,
                animation="flap",
            )
        )
        animations["flap"] = {"frames": ["bird-up", "bird", "bird-down", "bird"], "fps": 9}
        nodes.append(sprite("ground", "ground", 0, width, width, ground_height, layer=2))
        score = env.score
    nodes.append(
        {
            "id": "score",
            "kind": "text",
            "x": 12,
            "y": 8,
            "text": f"SCORE {score:04d}" if game == "snake" else f"{score} PIPES",
            "color": "#000000" if game == "snake" else "#ffffff",
            "hud": True,
            "layer": 10,
        }
    )
    return {
        "protocol": 1,
        "width": width,
        "height": height,
        "background": "#b2bd08" if game == "snake" else "#4ec0ca",
        "timestamp": time.time(),
        "nodes": nodes,
        "animations": animations,
    }
