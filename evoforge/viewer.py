"""Optional graphical Snake champion spectator; rendering never drives training."""

import argparse
import time
from pathlib import Path

from .core.checkpoints import safe_load
from .policy import Policy
from .snake import Snake


def load_champion(path):
    from .agents.serialization import load_policy

    return load_policy(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Live spectator for the saved champion")
    parser.add_argument("checkpoint", nargs="?", default="runs/hybrid/champion.pt")
    parser.add_argument("--fps", type=float, default=7)
    parser.add_argument(
        "--grid", action="store_true", help="display champion plus 3x3 sample policies"
    )
    parser.add_argument("--seed", type=int, default=900)
    parser.add_argument("--cell", type=int, default=30)
    args = parser.parse_args(argv)
    if args.fps <= 0 or args.cell < 8:
        parser.error("fps must be positive and cell at least 8")
    try:
        import pygame
    except ImportError as exc:
        raise SystemExit(
            "Install the optional graphical viewer: python -m pip install -e '.[viewer]'"
        ) from exc

    path = Path(args.checkpoint)
    pygame.init()
    if not pygame.display.get_init():
        raise SystemExit(
            "SDL video subsystem failed to initialize; check DISPLAY/WAYLAND_DISPLAY and pygame installation"
        )
    sample_path = path.with_name("spectator.pt")
    sample_mtime = None
    samples = []
    sample_envs = []
    sample_obs = []
    sample_seed = args.seed
    pygame.display.set_caption("EvoForge • Champion spectator (independent of training)")
    font = pygame.font.SysFont("monospace", 18)
    clock = pygame.time.Clock()
    screen = None
    model = cfg = env = obs = None
    count = 0
    seed = args.seed
    last_mtime = None
    next_reload = 0.0
    playing = True
    running = True
    while running:
        now = time.monotonic()
        if args.grid and now >= next_reload:
            try:
                stamp = sample_path.stat().st_mtime_ns
                if stamp != sample_mtime:
                    pack = safe_load(sample_path)
                    sample_cfg = pack["config"]
                    new_samples = []
                    for weights in pack["policies"][:9]:
                        agent = Policy(hidden=sample_cfg["hidden"])
                        agent.load_state_dict(weights)
                        agent.eval()
                        new_samples.append(agent)
                    samples = new_samples
                    sample_envs = [
                        Snake(sample_cfg["size"], sample_cfg["max_steps"]) for _ in samples
                    ]
                    sample_obs = [e.reset(args.seed + 51 + i) for i, e in enumerate(sample_envs)]
                    sample_mtime = stamp
            except (OSError, EOFError, RuntimeError, KeyError, ValueError):
                pass
        if now >= next_reload:
            next_reload = now + 2
            try:
                mtime = path.stat().st_mtime_ns
                if mtime != last_mtime:
                    new_model, new_cfg = load_champion(path)
                    if new_cfg.get("game", "snake") != "snake":
                        raise SystemExit(
                            "The graphical viewer supports Snake. Use evoforge play or the Textual spectator for other games."
                        )
                    model, cfg = new_model, new_cfg
                    env = Snake(cfg["size"], cfg["max_steps"])
                    obs = env.reset(seed)
                    last_mtime = mtime
                    screen = pygame.display.set_mode(
                        (
                            (
                                cfg["size"] * args.cell
                                + (3 * cfg["size"] * 12 + 24 if args.grid else 0)
                            ),
                            max(cfg["size"] * args.cell + 58, 3 * cfg["size"] * 12 + 58)
                            if args.grid
                            else cfg["size"] * args.cell + 58,
                        )
                    )
                    count = 0
            except (FileNotFoundError, EOFError, OSError, RuntimeError, KeyError, ValueError) as e:
                # A champion may not exist until the first evaluation finishes.
                if model is None:
                    pygame.display.set_caption(f"EvoForge • Awaiting champion ({type(e).__name__})")
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    playing = not playing
                elif event.key == pygame.K_r and env:
                    seed += 1
                    obs = env.reset(seed)
                    count = 0
        if model is None:
            if screen is None:
                screen = pygame.display.set_mode((480, 150))
            screen.fill((18, 24, 35))
            screen.blit(font.render("Waiting for champion.pt ...", True, (225, 225, 225)), (18, 55))
        else:
            if playing:
                if env.done:
                    seed += 1
                    obs = env.reset(seed)
                    count = 0
                obs, _, _, info = env.step(model.act(obs, deterministic=True))
                count += 1
            screen.fill((18, 29, 27))
            cell = args.cell
            for y in range(env.size):
                for x in range(env.size):
                    pygame.draw.rect(
                        screen,
                        (24, 48, 38) if (x + y) % 2 else (29, 54, 42),
                        (x * cell, y * cell, cell - 1, cell - 1),
                    )
            for j, (x, y) in enumerate(env.body):
                pygame.draw.rect(
                    screen,
                    (169, 231, 92) if j == 0 else (54, 195, 112),
                    (x * cell + 2, y * cell + 2, cell - 4, cell - 4),
                    border_radius=4,
                )
            if env.food is not None:
                x, y = env.food
                pygame.draw.circle(
                    screen, (244, 103, 111), (x * cell + cell // 2, y * cell + cell // 2), cell // 3
                )
            base = env.size * cell
            screen.blit(
                font.render(
                    f"Food: {env.food_eaten}   Step: {env.steps}   Seed: {seed}",
                    True,
                    (240, 240, 240),
                ),
                (8, base + 5),
            )
            screen.blit(
                font.render("SPACE pause  R new episode  X close", True, (172, 186, 182)),
                (8, base + 30),
            )
            if pygame.key.get_pressed()[pygame.K_x]:
                running = False
        if args.grid and model is not None:
            off = cfg["size"] * args.cell + 16
            miniature = 12
            # Render independent sample policy replays; no interference with training workers.
            for i, (agent, other) in enumerate(zip(samples, sample_envs)):
                if playing:
                    if other.done:
                        sample_seed += 1
                        sample_obs[i] = other.reset(sample_seed + i)
                    sample_obs[i], _, _, _ = other.step(
                        agent.act(sample_obs[i], deterministic=True)
                    )
                left = off + (i % 3) * (cfg["size"] * miniature + 4)
                top = (i // 3) * (cfg["size"] * miniature + 4)
                for bx, by in other.body:
                    pygame.draw.rect(
                        screen,
                        (70, 190, 102),
                        (left + bx * miniature, top + by * miniature, miniature - 1, miniature - 1),
                    )
                if other.food is not None:
                    bx, by = other.food
                    pygame.draw.circle(
                        screen,
                        (240, 90, 100),
                        (
                            left + bx * miniature + miniature // 2,
                            top + by * miniature + miniature // 2,
                        ),
                        miniature // 3,
                    )
                pygame.draw.rect(
                    screen,
                    (70, 80, 92),
                    (left, top, cfg["size"] * miniature, cfg["size"] * miniature),
                    1,
                )
        pygame.display.flip()
        clock.tick(args.fps if model is not None else 10)
    pygame.quit()


if __name__ == "__main__":
    main()
