from evoforge.core.checkpoints import safe_load, save
from evoforge.policy import Policy
from .factory import policy_for


def load_policy(path):
    data = safe_load(path)
    config = data["config"]
    model = Policy(**data["architecture"]) if "architecture" in data else policy_for(
        config.get("game", "snake"), config.get("hidden", 64), config.get("game_config"),
        config.get("size", 10), config.get("max_steps", 300))
    try:
        model.load_state_dict(data["state_dict"])
    except RuntimeError as exc:
        raise ValueError(f"Checkpoint architecture incompatible: {exc}") from exc
    model.eval()
    return model, config


def export_policy(path, model, config, **metadata):
    save(path, {"architecture": model.architecture, "config": config,
                "state_dict": model.state_dict(), **metadata})
