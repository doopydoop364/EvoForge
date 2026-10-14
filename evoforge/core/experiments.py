"""Budget-aware analytics and portable exports."""

import csv
import io
import json

from evoforge.service import read_metrics


def compare(supervisor, experiments, budget=None):
    if len(experiments) < 2:
        raise ValueError("Compare requires at least two experiments")
    runs = [supervisor.inspect(name) for name in experiments]
    signatures = [
        (
            r["config"].get("game", "snake"),
            r["game_version"],
            r["config"].get("game_config", {}),
            r["config"].get("size", 10),
            r["config"].get("max_steps", 300),
        )
        for r in runs
    ]
    if any(signature != signatures[0] for signature in signatures):
        raise ValueError("Comparison requires the same game version and environment configuration")
    histories = [read_metrics(supervisor.path(name)) for name in experiments]
    if any(not history or "environment_steps" not in history[-1] for history in histories):
        raise ValueError("Measured environment-step history is required for budget comparisons")
    matched = min(int(history[-1]["environment_steps"]) for history in histories)
    if budget is not None:
        if budget < 1:
            raise ValueError("budget must be positive")
        matched = min(matched, budget)
    comparisons = []
    for name, history in zip(experiments, histories):
        rows = [r for r in history if int(r["environment_steps"]) <= matched]
        if not rows:
            raise ValueError(f"{name} has no committed measurement within budget {matched}")
        latest = rows[-1]
        comparisons.append(
            {
                "experiment": name,
                "actual_environment_steps": latest["environment_steps"],
                "generation": latest["generation"],
                "training_fitness": latest["best_train"],
                "validation_fitness": latest["best_validation"],
                "wall_seconds": latest["wall_seconds"],
                "withheld_test": None,
            }
        )
    return {
        "environment_step_budget": matched,
        "results": comparisons,
        "note": "Last committed measurement at or below common budget; no interpolation. Validation is not withheld test data.",
    }


def export_metrics(directory, format="json"):
    rows = read_metrics(directory)
    if format == "json":
        return json.dumps(rows, indent=2, allow_nan=False)
    if format != "csv":
        raise ValueError("Export format must be csv or json")
    stream = io.StringIO(newline="")
    fields = list(dict.fromkeys(k for row in rows for k in row))
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
