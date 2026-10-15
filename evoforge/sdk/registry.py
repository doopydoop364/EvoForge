"""Installed package discovery; no upload, path or network code loading."""

import re
from importlib.metadata import entry_points

from .game import GamePlugin, dimensions

PLUGINS = {}
ERRORS = {}
_discovered = False


def register(plugin):
    if not isinstance(plugin, type) or not issubclass(plugin, GamePlugin):
        raise ValueError("Entry point must reference a GamePlugin subclass")
    info = plugin.info
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", info.id):
        raise ValueError("Game id must use lowercase letters, numbers, - or _")
    if info.sdk_version != 1:
        raise ValueError(f"{info.id}: unsupported SDK version {info.sdk_version}")
    if not info.name or not info.version:
        raise ValueError("Game name and version are required")
    from evoforge.games import GAMES

    if info.id in GAMES or (info.id in PLUGINS and PLUGINS[info.id] is not plugin):
        raise ValueError(f"Duplicate game id: {info.id}")
    PLUGINS[info.id] = plugin
    return plugin


def discover(refresh=False):
    global _discovered
    if _discovered and not refresh:
        return PLUGINS
    _discovered = True
    ERRORS.clear()
    for entry in entry_points(group="evoforge.games"):
        try:
            register(entry.load())
        except Exception as exc:
            ERRORS[entry.name] = f"{type(exc).__name__}: {exc}"
    return PLUGINS


def create(game, config=None, max_steps=300):
    from .game import FlattenAdapter

    discover()
    if game not in PLUGINS:
        raise ValueError(f"Unknown installed game: {game}")
    plugin = PLUGINS[game](**(config or {}))
    try:
        dimensions(plugin)
        return FlattenAdapter(plugin, max_steps)
    except Exception:
        plugin.close()
        raise
