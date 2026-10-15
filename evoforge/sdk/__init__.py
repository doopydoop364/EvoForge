from .game import FlattenAdapter, GameInfo, GamePlugin, dimensions
from .registry import discover, register
from .validation import validate_game

__all__ = [
    "FlattenAdapter",
    "GameInfo",
    "GamePlugin",
    "dimensions",
    "discover",
    "register",
    "validate_game",
]
