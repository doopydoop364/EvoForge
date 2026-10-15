"""Standard-library terminal UI; trainer runs in a separate child process."""

import csv
import curses
import json
import sys
from pathlib import Path

from .core.checkpoints import safe_load


def _lines(path, limit=24):
    try:
        return path.read_text(errors="replace").splitlines()[-limit:]
    except FileNotFoundError:
        return []


def _metric(path):
    try:
        with path.open(newline="") as stream:
            values = list(csv.DictReader(stream))
        return values[-1] if values else None
    except (OSError, ValueError):
        return None


def _safe_add(scr, row, col, message, attr=0):
    h, w = scr.getmaxyx()
    if 0 <= row < h and 0 <= col < w:
        try:
            scr.addnstr(row, col, str(message), max(0, w - col - 1), attr)
        except curses.error:
            pass


def _history(path):
    try:
        with path.open(newline="") as stream:
            return list(csv.DictReader(stream))
    except (OSError, ValueError):
        return []


def _spark(values, length=48):
    if not values:
        return "(no data)"
    values = values[-length:]
    lo, hi = min(values), max(values)
    chars = "▁▂▃▄▅▆▇█"
    return "".join(
        chars[min(7, int((v - lo) / (hi - lo) * 7))] if hi != lo else chars[3] for v in values
    )


def _latest_timing(directory):
    for line in reversed(_lines(directory / "timings.jsonl", 1)):
        try:
            return json.loads(line)
        except (ValueError, TypeError):
            pass
    return None


SETTINGS_FIELDS = [
    ("game", "Game", "choice", ["snake", "flappy"]),
    ("mode", "Training mode", "choice", ["evolution", "hybrid", "ppo"]),
    ("population", "Population", "int", (2, 4096, 1)),
    ("generations", "Generations", "int", (1, 1000000, 10)),
    ("elites", "Elite agents", "int", (1, 4095, 1)),
    ("ppo_candidates", "PPO candidates", "int", (0, 4096, 1)),
    ("ppo_episodes", "PPO episodes", "int", (1, 10000, 1)),
    ("eval_episodes", "Evaluation episodes", "int", (1, 10000, 1)),
    ("size", "Board size", "int", (5, 128, 1)),
    ("max_steps", "Maximum steps", "int", (1, 100000, 25)),
    ("seed", "Random seed", "int", (0, 2147483647, 1)),
    ("hidden", "Hidden neurons", "int", (8, 2048, 8)),
]


def _settings_defaults():
    from dataclasses import asdict

    from .trainer import Config

    return asdict(Config())


def _change_setting(settings, key, direction):
    item = next(row for row in SETTINGS_FIELDS if row[0] == key)
    if item[2] == "choice":
        choices = item[3]
        settings[key] = choices[(choices.index(settings[key]) + direction) % len(choices)]
    else:
        lo, hi, step = item[3]
        settings[key] = max(lo, min(hi, int(settings[key]) + direction * step))


def _validate_settings(settings):
    from .trainer import Config

    cfg = Config(**settings)
    cfg.validate()
    if cfg.elites >= cfg.population:
        raise ValueError("Elite agents must be fewer than population")
    if cfg.ppo_candidates > cfg.population:
        raise ValueError("PPO candidates cannot exceed population")
    if cfg.size < 5:
        raise ValueError("Board size must be at least 5")
    return cfg


def _edit_settings(screen, directory):
    if (directory / "checkpoint.pt").exists():
        return "Existing checkpoint: use E to extend generations; start a new run to change other settings."
    path = directory / "config.json"
    try:
        settings = _settings_defaults()
        if path.exists():
            settings.update(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError) as exc:
        return f"Cannot load settings: {exc}"
    selected = 0
    offset = 0
    message = (
        "Arrows navigate · Left/Right adjust · Enter edit · Click select · S save · Esc cancel"
    )
    screen.timeout(100)
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        visible = max(1, height - 10)
        offset = (
            min(max(0, selected - visible + 1), offset)
            if selected >= offset + visible
            else min(offset, selected)
        )
        _safe_add(screen, 1, 3, "EVOFORGE  /  EXPERIMENT SETTINGS", curses.A_BOLD)
        _safe_add(screen, 2, 3, "Interactive configuration · changes are not applied until saved")
        _safe_add(screen, 4, 3, "PARAMETER", curses.A_BOLD)
        _safe_add(screen, 4, max(23, width // 2), "VALUE", curses.A_BOLD)
        for pos in range(offset, min(len(SETTINGS_FIELDS), offset + visible)):
            key, label, kind, _ = SETTINGS_FIELDS[pos]
            row = 5 + pos - offset
            selected_attr = curses.A_REVERSE if pos == selected else 0
            _safe_add(screen, row, 3, ("▶ " if pos == selected else "  ") + label, selected_attr)
            value = (
                ("◀ " + str(settings[key]) + " ▶")
                if kind == "choice"
                else str(settings[key]) + "  (-/+)"
            )
            _safe_add(screen, row, max(23, width // 2), value, selected_attr)
        _safe_add(
            screen,
            max(0, height - 4),
            3,
            "↑↓ select    ←→ adjust    Enter edit    Mouse select/adjust",
        )
        _safe_add(screen, max(0, height - 3), 3, "S save    Esc cancel    Home/End jump")
        _safe_add(screen, max(0, height - 2), 3, message[: max(1, width - 6)])
        screen.refresh()
        key = screen.getch()
        if key == -1:
            continue
        if key in (27, ord("q"), ord("Q")):
            return "Settings changes discarded."
        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(SETTINGS_FIELDS) - 1, selected + 1)
        elif key == curses.KEY_HOME:
            selected = 0
        elif key == curses.KEY_END:
            selected = len(SETTINGS_FIELDS) - 1
        elif key in (curses.KEY_LEFT, ord("-"), ord("h")):
            _change_setting(settings, SETTINGS_FIELDS[selected][0], -1)
        elif key in (curses.KEY_RIGHT, ord("+"), ord("l")):
            _change_setting(settings, SETTINGS_FIELDS[selected][0], 1)
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, state = curses.getmouse()
                if state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    if 5 <= my < 5 + visible and my - 5 + offset < len(SETTINGS_FIELDS):
                        selected = my - 5 + offset
                        if mx >= max(23, width // 2):
                            _change_setting(settings, SETTINGS_FIELDS[selected][0], 1)
            except curses.error:
                pass
        elif key in (10, 13, curses.KEY_ENTER):
            k, label, kind, _ = SETTINGS_FIELDS[selected]
            if kind == "choice":
                _change_setting(settings, k, 1)
            else:
                _safe_add(
                    screen, max(0, height - 2), 3, f"Enter {label}: ".ljust(max(0, width - 5))
                )
                screen.refresh()
                curses.echo()
                curses.curs_set(1)
                screen.timeout(-1)
                try:
                    raw = (
                        screen.getstr(max(0, height - 2), min(width - 2, 4 + len(label) + 8), 18)
                        .decode()
                        .strip()
                    )
                    if raw:
                        settings[k] = int(raw)
                    message = "Value updated; press S to validate and save."
                except (ValueError, UnicodeDecodeError):
                    message = "Invalid integer; previous value retained."
                finally:
                    curses.noecho()
                    curses.curs_set(0)
                    screen.timeout(100)
        elif key in (ord("s"), ord("S")):
            try:
                _validate_settings(settings)
                directory.mkdir(parents=True, exist_ok=True)
                from .supervisor import Supervisor

                manager = Supervisor(directory.resolve().parent)
                manager.register(directory.name)
                manager.update(directory.name, settings)
                return "Settings saved. Press S to start training."
            except (ValueError, TypeError, OSError) as exc:
                message = f"Cannot save: {exc}"


def _extend(screen, directory):
    checkpoint = directory / "checkpoint.pt"
    if not checkpoint.exists():
        return "No checkpoint to extend; configure a new run first."
    try:
        saved = safe_load(checkpoint)
        cfg = dict(saved["config"])
        current = max(int(cfg["generations"]), int(saved["generation"]))
        curses.echo()
        curses.curs_set(1)
        screen.nodelay(False)
        screen.erase()
        _safe_add(
            screen, 2, 2, f"Completed {saved['generation']} generations. Current target {current}."
        )
        _safe_add(screen, 4, 2, "Add how many generations? (e.g. 100): ")
        screen.refresh()
        raw = screen.getstr(4, 43, 12).decode().strip()
        if not raw:
            return "Extension canceled."
        extra = int(raw)
        if extra < 1 or extra > 1000000:
            return "Enter a positive number up to 1000000."
        cfg["generations"] = current + extra
        from .supervisor import Supervisor

        manager = Supervisor(directory.resolve().parent)
        manager.register(directory.name)
        manager.update(directory.name, cfg)
        return f"Extended run to {cfg['generations']} generations. Press S to resume."
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return f"Extension failed: {exc}"
    finally:
        curses.noecho()
        curses.curs_set(0)
        screen.nodelay(True)


def _command(directory, resume):
    cfgfile = directory / "config.json"
    if cfgfile.exists():
        config = json.loads(cfgfile.read_text())
        flags = []
        for key in (
            "game",
            "mode",
            "population",
            "generations",
            "elites",
            "ppo_candidates",
            "ppo_episodes",
            "eval_episodes",
            "size",
            "max_steps",
            "seed",
            "hidden",
        ):
            flags += [
                "--" + key.replace("_", "-"),
                str(config.get(key, "snake") if key == "game" else config[key]),
            ]
    else:
        flags = [
            "--mode",
            "hybrid",
            "--population",
            "24",
            "--generations",
            "30",
            "--ppo-candidates",
            "3",
            "--output",
            str(directory),
        ]
    if "--output" not in flags:
        flags += ["--output", str(directory)]
    if resume:
        flags += ["--resume"]
    return [sys.executable, "-m", "evoforge.cli", "train", *flags]


def launch(directory):
    if (directory / "checkpoint.pt").exists():
        return _command(directory, True)
    return _command(directory, False)


def run(screen, directory):
    """Standard-library fallback using the same durable supervisor as Textual."""
    from .core.checkpoints import atomic_json
    from .supervisor import Supervisor
    from .supervisor.lifecycle import ACTIVE

    manager = Supervisor(directory.resolve().parent)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / "config.json").exists():
        atomic_json(directory / "config.json", _settings_defaults())
    manager.register(directory.name)
    curses.curs_set(0)
    screen.timeout(200)
    inspector = None
    status = "Workers continue after this dashboard exits."
    show_graph = False
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if inspector:
            inspector.tick()
            inspector.render(screen, _safe_add)
            screen.refresh()
            key = screen.getch()
            if key in (ord("b"), ord("v"), ord("q")):
                inspector = None
            elif key != -1:
                inspector.handle(key)
            continue
        row = manager.inspect(directory.name)
        _safe_add(screen, 0, 2, "EVOFORGE / TRAINING CONTROL", curses.A_BOLD)
        _safe_add(
            screen,
            1,
            2,
            "S Start  P Pause/Resume  X Stop  V Replay  G Analytics  C Settings  E Extend  Q Detach",
        )
        _safe_add(screen, 3, 2, f"{directory.name} | {row['status']} | {status}")
        latest = _metric(directory / "metrics.csv")
        if latest:
            _safe_add(
                screen,
                5,
                2,
                f"Generation {latest.get('generation')} | Best {latest.get('best_train')} | Mean {latest.get('mean_train')}",
            )
        if show_graph:
            history = _history(directory / "metrics.csv")
            for y, field in [(7, "best_train"), (9, "mean_train")]:
                _safe_add(screen, y, 2, field + ": " + _spark([float(r[field]) for r in history]))
        else:
            for y, line in enumerate(_lines(directory / "training.log", max(1, height - 9)), 7):
                _safe_add(screen, y, 2, line)
        screen.refresh()
        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            return
        try:
            if key in (ord("s"), ord("S")):
                manager.start(directory.name)
                status = "Worker starting"
            elif key in (ord("p"), ord("P")):
                manager.request(directory.name, "resume" if row["status"] == "PAUSED" else "pause")
                status = "Control request submitted"
            elif key in (ord("x"), ord("X")):
                manager.request(directory.name, "stop")
                status = "Stop requested"
            elif key in (ord("v"), ord("V")):
                from .terminal_viewer import TerminalInspector

                inspector = TerminalInspector(directory)
            elif key in (ord("g"), ord("G")):
                show_graph = not show_graph
            elif key in (ord("c"), ord("C")):
                status = (
                    "Stop training before editing"
                    if row["status"] in ACTIVE
                    else _edit_settings(screen, directory)
                )
            elif key in (ord("e"), ord("E")):
                status = (
                    "Stop training before extending"
                    if row["status"] in ACTIVE
                    else _extend(screen, directory)
                )
        except (ValueError, OSError, KeyError) as exc:
            status = str(exc)


def main(argv=None):
    import argparse

    p = argparse.ArgumentParser(description="EvoForge terminal dashboard")
    p.add_argument("--output", default="runs/hybrid")
    args = p.parse_args(argv)
    curses.wrapper(run, Path(args.output))


if __name__ == "__main__":
    main()
