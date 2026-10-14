"""Persistent user interface preferences (independent of training runs)."""
import json
import os
from pathlib import Path


def preference_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "evoforge" / "preferences.json"


def load_preferences(path=None):
    try:
        data = json.loads(Path(path or preference_path()).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_preferences(changes, path=None):
    target = Path(path or preference_path())
    settings = load_preferences(target)
    settings.update(changes)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n")
    temporary.replace(target)
