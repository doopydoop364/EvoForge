"""EvoForge command line; optional frontends are imported only on request."""

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path


def emit(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def parser_for_cli():
    parser = argparse.ArgumentParser(description="EvoForge universal game learning platform")
    commands = parser.add_subparsers(dest="command")
    for name in ("tui", "dashboard"):
        ui = commands.add_parser(name)
        ui.add_argument("--output", default="runs/hybrid")
    commands.add_parser("version")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--root", default="runs")
    games = commands.add_parser("games")
    games.add_argument("action", choices=["list", "inspect", "validate"])
    games.add_argument("game_id", nargs="?")
    games.add_argument("--game-config", default="{}", help="JSON plugin configuration")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("path")
    migrate.add_argument("--apply", action="store_true", help="default is dry-run")
    api = commands.add_parser("api")
    api.add_argument("action", choices=["serve"])
    api.add_argument("--root", default="runs")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8765)
    workers = commands.add_parser("workers")
    workers.add_argument(
        "action", choices=["list", "status", "start", "recover", "pause", "resume", "stop"]
    )
    workers.add_argument("id", nargs="?")
    workers.add_argument("--root", default="runs")
    experiments = commands.add_parser("experiments")
    experiments.add_argument(
        "action",
        choices=[
            "list",
            "create",
            "inspect",
            "compare",
            "duplicate",
            "rename",
            "archive",
            "unarchive",
            "export",
        ],
    )
    experiments.add_argument("ids", nargs="*")
    experiments.add_argument("--root", default="runs")
    experiments.add_argument("--config-file")
    experiments.add_argument("--game", default=None)
    experiments.add_argument("--mode", choices=["evolution", "ppo", "hybrid"], default=None)
    experiments.add_argument("--budget", type=int)
    experiments.add_argument("--format", choices=["csv", "json"], default="json")
    train = commands.add_parser("train")
    for flag, kwargs in {
        "mode": dict(choices=["evolution", "hybrid", "ppo"]),
        "game": {},
        **{
            key: dict(type=int)
            for key in (
                "population",
                "generations",
                "elites",
                "ppo-candidates",
                "ppo-episodes",
                "eval-episodes",
                "size",
                "max-steps",
                "seed",
                "hidden",
                "environment-step-budget",
            )
        },
        "mutation-probability": dict(type=float),
        "mutation-sigma": dict(type=float),
    }.items():
        train.add_argument("--" + flag, **kwargs)
    train.add_argument("--hidden-widths", help="comma separated MLP widths, e.g. 64,32")
    train.add_argument("--game-config", help="JSON object of plugin constructor arguments")
    train.add_argument("--config-file")
    train.add_argument("--output", default="runs/snake-hybrid")
    train.add_argument("--resume", action="store_true")
    train.add_argument("--background", action="store_true")
    play = commands.add_parser("play")
    play.add_argument("checkpoint")
    play.add_argument("--seed", type=int, default=123)
    play.add_argument("--fps", type=float, default=7)
    baseline = commands.add_parser("baseline")
    baseline.add_argument("game")
    baseline.add_argument("--episodes", type=int, default=10)
    baseline.add_argument("--seed", type=int, default=8000000)
    baseline.add_argument("--heuristic", action="store_true")
    return parser


def train_command(args):
    from .supervisor import Supervisor
    from .trainer import Config

    directory = Path(args.output).expanduser().resolve()
    manager = Supervisor(directory.parent)
    manager.path(directory.name)
    if (directory / "checkpoint.pt").exists() and not args.resume:
        raise ValueError("Checkpoint exists: use --resume or create a new experiment")
    values = asdict(Config())
    source = Path(args.config_file) if args.config_file else directory / "config.json"
    if source.is_file():
        values.update(json.loads(source.read_text()))
    for field in values:
        if hasattr(args, field) and getattr(args, field) is not None:
            values[field] = getattr(args, field)
    if args.hidden_widths:
        values["hidden"] = [int(width) for width in args.hidden_widths.split(",")]
    if args.game_config:
        values["game_config"] = json.loads(args.game_config)
    cfg = Config(**values)
    if directory.exists() and (directory / "config.json").exists():
        manager.register(directory.name)
        manager.update(directory.name, cfg)
    elif directory.exists():
        # Preserve existing directory contents while initializing a config.
        from .core.checkpoints import atomic_json

        cfg.validate()
        atomic_json(directory / "config.json", asdict(cfg))
        manager.register(directory.name)
    else:
        manager.create(directory.name, cfg)
    emit(manager.start(directory.name))
    if not args.background:
        try:
            while manager.inspect(directory.name)["status"] in (
                "STARTING",
                "RUNNING",
                "PAUSED",
                "STOPPING",
            ):
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("Detached; worker continues. Use evoforge workers for control.")
        else:
            result = manager.inspect(directory.name)
            emit(result)
            if result["status"] == "FAILED":
                raise SystemExit(1)


def dispatch(args, parser):
    if args.command == "version":
        from . import __version__

        print(__version__)
    elif args.command == "doctor":
        from .doctor import diagnose

        emit(diagnose(args.root))
    elif args.command == "games":
        from .games import available_games, game_spec, game_version
        from .sdk import validate_game
        from .sdk.registry import ERRORS

        if args.action == "list":
            emit({"games": available_games(), "errors": ERRORS})
        else:
            if not args.game_id:
                parser.error("game id required")
            if args.action == "validate":
                emit(validate_game(args.game_id, json.loads(args.game_config)))
            else:
                spec = game_spec(args.game_id)
                emit(
                    {
                        **{k: v for k, v in asdict(spec).items() if k != "environment"},
                        "version": game_version(args.game_id),
                    }
                )
    elif args.command == "migrate":
        from .core.checkpoints import migrate

        emit(migrate(args.path, dry_run=not args.apply))
    elif args.command in ("tui", "dashboard"):
        if args.command == "tui":
            from .tui import main

            main(args.output)
        else:
            from .dashboard import main

            main(["--output", args.output])
    elif args.command == "api":
        import uvicorn

        from .api.app import create_app

        uvicorn.run(create_app(args.root, bind_host=args.host), host=args.host, port=args.port)
    elif args.command == "train":
        train_command(args)
    elif args.command == "workers":
        from .supervisor import Supervisor

        manager = Supervisor(args.root)
        if args.action == "list":
            emit(manager.workers())
        elif not args.id:
            parser.error("experiment id required")
        elif args.action == "status":
            emit(manager.inspect(args.id))
        elif args.action in ("start", "recover"):
            emit(manager.start(args.id))
        else:
            emit(manager.request(args.id, args.action))
    elif args.command == "experiments":
        from .core.experiments import compare, export_metrics
        from .supervisor import Supervisor
        from .trainer import Config

        manager = Supervisor(args.root)
        if args.action == "list":
            emit(manager.list())
        elif not args.ids:
            parser.error("experiment id(s) required")
        elif args.action == "create":
            values = (
                json.loads(Path(args.config_file).read_text())
                if args.config_file
                else asdict(Config())
            )
            if args.game:
                values["game"] = args.game
            if args.mode:
                values["mode"] = args.mode
            emit(manager.create(args.ids[0], values))
        elif args.action == "inspect":
            manager.register(args.ids[0])
            emit(manager.inspect(args.ids[0]))
        elif args.action == "compare":
            emit(compare(manager, args.ids, args.budget))
        elif args.action == "export":
            manager.inspect(args.ids[0])
            print(export_metrics(manager.path(args.ids[0]), args.format))
        elif args.action in ("duplicate", "rename"):
            if len(args.ids) != 2:
                parser.error("source and destination ids required")
            emit(getattr(manager, args.action)(*args.ids))
        else:
            emit(manager.archive(args.ids[0], args.action == "archive"))
    elif args.command == "play":
        from .agents.serialization import load_policy
        from .games import close_env, make_env

        if args.fps <= 0:
            raise ValueError("fps must be positive")
        model, cfg = load_policy(args.checkpoint)
        env = make_env(
            cfg.get("game", "snake"), cfg["size"], cfg["max_steps"], cfg.get("game_config")
        )
        try:
            obs, done = env.reset(args.seed), False
            while not done:
                obs, _, done, info = env.step(model.act(obs, deterministic=True))
                print("\033[2J\033[H" + env.render() + "\n" + json.dumps(info), flush=True)
                time.sleep(1 / args.fps)
        finally:
            close_env(env)
    elif args.command == "baseline":
        from .core.evaluation import baseline

        if args.episodes < 1:
            raise ValueError("episodes must be positive")
        emit(
            baseline(
                args.game, range(args.seed, args.seed + args.episodes), heuristic=args.heuristic
            )
        )


def main(argv=None):
    parser = parser_for_cli()
    args = parser.parse_args(argv)
    if args.command is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            args.command = "tui" if importlib.util.find_spec("textual") else "dashboard"
            args.output = "runs/hybrid"
        else:
            parser.print_help()
            print(
                "\nHeadless session: use evoforge train, workers, or api serve. For an interactive SSH terminal use evoforge tui."
            )
            return
    try:
        dispatch(args, parser)
    except ImportError as exc:
        parser.exit(2, f"Missing dependency: {exc}. Install the matching tui/api extra.\n")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"EvoForge: {exc}\n")


if __name__ == "__main__":
    main()
