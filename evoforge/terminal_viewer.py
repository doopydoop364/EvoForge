"""SSH-friendly, curses-native Snake spectator. No SDL or display server required."""

import curses
import time
from collections import deque
from pathlib import Path

from .core.checkpoints import safe_load
from .games import game_spec, make_env, metric


class TerminalInspector:
    def __init__(self, directory, fps=7):
        self.directory = Path(directory)
        self.fps = fps
        self.zoom = 0
        self.show_analytics = True
        self.focus_only = False
        self.telemetry = []
        self.prev_food = []
        self.death_reasons = []
        self.episode_counts = []
        self.max_food = []
        self.mini_scale = 1  # terminal characters per cell for side panels
        self.focus_paused = set()
        self.focus_seed = {}
        self.focus_last_step = {}
        self.auto_update = False  # Stay with one checkpoint until user requests an update.
        self.selection = 0  # 0 champion, 1..9 archived population snapshots
        self.playing = True
        self.seed = 900
        self.last_step = 0.0
        self.last_scan = 0.0
        self.stamps = {}
        self.models = []
        self.envs = []
        self.observations = []
        self.info = "Waiting for a saved champion. Train at least one generation."
        self.reload(force=True)

    def reload(self, force=False):
        if not (force or self.auto_update):
            return
        if not force and time.monotonic() - self.last_scan < 2:
            return
        self.last_scan = time.monotonic()
        champion = self.directory / "champion.pt"
        spectator = self.directory / "spectator.pt"
        stamps = tuple(p.stat().st_mtime_ns if p.exists() else None for p in (champion, spectator))
        if not force and stamps == self.stamps.get("files"):
            return
        self.stamps["files"] = stamps
        try:
            from .agents import policy_for
            from .viewer import load_champion

            if not champion.is_file():
                return
            model, config = load_champion(champion)
            models = [model]
            if spectator.is_file():
                package = safe_load(spectator)
                if package.get("config", {}).get("size") == config["size"] and package.get(
                    "config", {}
                ).get("game", "snake") == config.get("game", "snake"):
                    for weights in package.get("policies", [])[:9]:
                        other = policy_for(
                            config.get("game", "snake"),
                            config["hidden"],
                            config.get("game_config"),
                            config["size"],
                            config["max_steps"],
                        )
                        other.load_state_dict(weights)
                        other.eval()
                        models.append(other)
            self.models = models
            self.game = config.get("game", "snake")
            self.envs = [
                make_env(self.game, config["size"], config["max_steps"], config.get("game_config"))
                for _ in models
            ]
            self.observations = [env.reset(self.seed + i) for i, env in enumerate(self.envs)]
            self.selection = min(self.selection, len(models) - 1)
            self.telemetry = [deque(maxlen=300) for _ in models]
            self.prev_food = [0] * len(models)
            self.death_reasons = [
                dict(wall=0, body=0, starvation=0, timeout=0, win=0, collision=0) for _ in models
            ]
            self.episode_counts = [0] * len(models)
            self.max_food = [0] * len(models)
            self.focus_paused.clear()
            self.focus_last_step.clear()
            self.info = f"Loaded champion + {len(models) - 1} population snapshots."
        except Exception as exc:
            self.info = f"Cannot load spectator: {type(exc).__name__}: {exc}"

    def handle(self, key):
        if key in (ord(" "),):
            if self.selection in self.focus_paused:
                self.focus_paused.remove(self.selection)
            else:
                self.focus_paused.add(self.selection)
        elif key in (ord("n"), ord("N")):
            self.reload(force=True)
            self.info += " (manual refresh)"
        elif key in (ord("u"), ord("U")):
            self.auto_update = not self.auto_update
            self.info = (
                "Auto-update ON (only between games)."
                if self.auto_update
                else "Champion LOCKED; press N for newest."
            )
        elif key in (ord("a"), ord("A")):
            self.show_analytics = not self.show_analytics
        elif key in (ord("f"), ord("F")):
            self.focus_only = not self.focus_only
        elif key in (ord("r"), ord("R")):
            self.seed += 100
            if self.envs:
                i = self.selection
                self.observations[i] = self.envs[i].reset(self.seed + i)
                if i < len(self.prev_food):
                    self.prev_food[i] = 0
        elif key in (
            ord("0"),
            ord("1"),
            ord("2"),
            ord("3"),
            ord("4"),
            ord("5"),
            ord("6"),
            ord("7"),
            ord("8"),
            ord("9"),
        ):
            index = key - ord("0")
            if index < len(self.models):
                self.selection = index
        elif key in (9, ord("]"), curses.KEY_RIGHT):
            if self.models:
                self.selection = (self.selection + 1) % len(self.models)
        elif key in (curses.KEY_BTAB, ord("["), curses.KEY_LEFT):
            if self.models:
                self.selection = (self.selection - 1) % len(self.models)
        elif key in (ord("m"), ord("M")):
            self.mini_scale = max(1, self.mini_scale - 1)
        elif key in (ord("k"), ord("K")):
            self.mini_scale = min(4, self.mini_scale + 1)
        elif key in (ord("+"), ord("=")):
            self.fps = min(30, self.fps + 1)
        elif key == ord("-"):
            self.fps = max(1, self.fps - 1)
        elif key in (ord("z"), ord("Z")):
            self.zoom = min(4, self.zoom + 1)
        elif key in (ord("x"), ord("X")):
            self.zoom = max(0, self.zoom - 1)

    def tick(self):
        now = time.monotonic()
        if not self.playing or not self.models or now - self.last_step < 1 / self.fps:
            return
        self.last_step = now
        for i, (model, env) in enumerate(zip(self.models, self.envs)):
            if i in self.focus_paused:
                continue
            if env.done:
                if i == 0 and self.auto_update:
                    self.reload()
                    # Reload replaces environments; finish this tick to avoid stepping stale instances.
                    if self.envs[i] is not env:
                        return
                self.seed += 1
                self.observations[i] = env.reset(self.seed + i)
                if i < len(self.prev_food):
                    self.prev_food[i] = 0
            self.observations[i], _, ended, _ = env.step(
                model.act(self.observations[i], deterministic=True)
            )
            if i < len(self.prev_food):
                if metric(env) > self.prev_food[i]:
                    self.telemetry[i].append((env.steps, metric(env)))
                self.prev_food[i] = metric(env)
                self.max_food[i] = max(self.max_food[i], metric(env))
                if ended:
                    self.episode_counts[i] += 1
                    self.death_reasons[i][self._ending(env)] += 1

    @staticmethod
    def _ending(env):
        """Determine terminal cause from the final position and episode constraints."""
        if not hasattr(env, "body"):
            return "collision" if env.steps < env.max_steps else "timeout"
        if env.food is None:
            return "win"
        dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[env.direction]
        x, y = env.body[0]
        nx, ny = x + dx, y + dy
        if nx < 0 or ny < 0 or nx >= env.size or ny >= env.size:
            return "wall"
        if (nx, ny) in list(env.body)[:-1]:
            return "body"
        if env.steps >= env.max_steps:
            return "timeout"
        return "starvation"

    @staticmethod
    def sparkline(values, max_width=32):
        """Text-only graph that remains readable over a basic SSH terminal."""
        blocks = " .:-=+*#%@"
        values = list(values)[-max_width:]
        if not values:
            return "(no completed episodes yet)"
        low = min(values)
        high = max(values)
        if high == low:
            return blocks[-1 if high else 0] * len(values)
        return "".join(
            blocks[min(len(blocks) - 1, int((v - low) / (high - low) * (len(blocks) - 1)))]
            for v in values
        )

    @staticmethod
    def layout(width, height, board_size, num_agents, mini_scale=1):
        """Calculate viewport positions; never place an incomplete board on screen.

        Returns (focus tuple, list of (index, x, y, scale) tuples), using
        index 0..N-1 for agents and scale in terminal characters per cell.
        """
        if num_agents < 1 or width < board_size + 5 or height < board_size + 9:
            return None, []
        top, left = 5, 2
        usable_h = height - top - 3
        focus_scale = max(1, min(3, (usable_h - 3) // board_size, (width - 5) // (board_size * 2)))
        focus_w = board_size * focus_scale + 2
        focus = (left, top, focus_scale)
        side_x = left + focus_w + 3
        remaining_w = width - side_x - 2
        if remaining_w < board_size + 2 or usable_h < board_size + 2:
            return focus, []
        # Increase or decrease visible mini-agent count when resizing the terminal
        # or changing the requested mini scale.
        scale = max(1, mini_scale)
        mini_w = board_size * scale + 2
        mini_h = board_size + 5
        cols = remaining_w // (mini_w + 2)
        rows = usable_h // (mini_h + 1)
        positions = []
        for slot in range(min(num_agents - 1, cols * rows)):
            c = slot % cols
            r = slot // cols
            positions.append((slot, side_x + c * (mini_w + 2), top + r * (mini_h + 1), scale))
        return focus, positions

    def _colors(self, scr):
        try:
            if not curses.has_colors():
                return None
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(21, curses.COLOR_GREEN, -1)
            curses.init_pair(22, curses.COLOR_RED, -1)
            curses.init_pair(23, curses.COLOR_CYAN, -1)
            curses.init_pair(24, curses.COLOR_YELLOW, -1)
            return (
                curses.color_pair(21),
                curses.color_pair(22),
                curses.color_pair(23),
                curses.color_pair(24),
            )
        except (curses.error, ValueError):
            return None

    def _board(self, scr, put, index, x, y, scale, colored=False, colors=None):
        env = self.envs[index]
        size = env.size
        width = size * scale + 2
        label = "CHAMPION" if index == 0 else f"AGENT {index}"
        if index == self.selection:
            label = "> " + label
        latest = f"{label}  {game_spec(getattr(self, 'game', 'snake')).score_label}:{metric(env)}  steps:{env.steps}"
        put(
            scr,
            y,
            x,
            latest[: width + 1] if index != self.selection else latest[: min(42, max(width, 28))],
            curses.A_BOLD if index == self.selection else 0,
        )
        # Terminal cards are bordered, with a distinct selected/colored primary board.
        put(scr, y + 1, x, "+" + "-" * (width - 2) + "+")
        rows = env.render().splitlines()
        for yy, row in enumerate(rows):
            put(scr, y + 2 + yy, x, "|")
            if not colored or not colors:
                put(scr, y + 2 + yy, x + 1, "".join(c * scale for c in row))
            else:
                for xx, ch in enumerate(row):
                    attr = (
                        (colors[3] | curses.A_BOLD)
                        if ch == "H"
                        else colors[0]
                        if ch in ("o", "#")
                        else colors[1]
                        if ch == "*"
                        else 0
                    )
                    put(scr, y + 2 + yy, x + 1 + xx * scale, ch * scale, attr)
            put(scr, y + 2 + yy, x + width - 1, "|")
        put(scr, y + 2 + size, x, "+" + "-" * (width - 2) + "+")
        if index < len(self.max_food):
            put(
                scr,
                y + 3 + size,
                x,
                f"best:{self.max_food[index]} games:{self.episode_counts[index]}"[: width + 6],
            )

    def render(self, scr, put):
        height, width = scr.getmaxyx()
        put(
            scr,
            0,
            2,
            f"EVOFORGE / {getattr(self, 'game', 'snake').upper()} INSPECTOR",
            curses.A_BOLD,
        )
        put(
            scr, 1, 2, "[TAB / 0-9] focus  [F] solo/grid  [A] analytics  [SPACE] pause  [R] restart"
        )
        put(scr, 2, 2, "[K/M] mini size  [N] newest  [U] auto/lock  [+/-] speed  [B] back")
        pause = "PAUSED" if self.selection in self.focus_paused else "PLAYING"
        put(
            scr,
            3,
            2,
            f"Agent {self.selection}: {pause} | {self.fps} moves/sec | {'AUTO' if self.auto_update else 'LOCKED'} | {self.info}",
        )
        if not self.models:
            put(scr, 5, 2, self.info)
            return
        env = self.envs[self.selection]
        focus, mini = self.layout(width, height, env.size, len(self.models), self.mini_scale)
        if focus is None:
            put(
                scr,
                5,
                2,
                f"Terminal too small. Need at least {env.size + 5} columns x {env.size + 9} rows.",
            )
            return
        fx, fy, fs = focus
        # Enlarge the focused board when grid is hidden; never draw beyond terminal bounds.
        if self.focus_only:
            fs = max(1, min(4, (width - 6) // env.size, (height - 12) // env.size))
            mini = []
        self._board(scr, put, self.selection, fx, fy, fs, True, self._colors(scr))
        other_indices = [i for i in range(len(self.models)) if i != self.selection]
        for slot, x, y, scale in mini:
            self._board(scr, put, other_indices[slot], x, y, scale, False)
        if self.show_analytics:
            self._analytics(scr, put, height, width)
        put(
            scr,
            height - 2,
            2,
            f"Viewing {1 + len(mini)} agents; {len(other_indices) - len(mini)} hidden | "
            f"focused agent controls only | CPU-only saved-policy replay",
        )

    def _analytics(self, scr, put, height, width):
        # Right- or bottom-side details; automatically hide if terminal space is scarce.
        if not self.envs or width < 60 or height < 25:
            return
        env = self.envs[self.selection]
        size = env.size
        focus, mini = self.layout(width, height, size, len(self.models), self.mini_scale)
        if focus is None:
            return
        board_bottom = (
            5
            + size
            * (
                max(1, min(4, (width - 6) // size, (height - 12) // size))
                if self.focus_only
                else focus[2]
            )
            + 5
        )
        x, y = (3, board_bottom + 1)
        if y + 5 >= height - 2:
            # Reserve far-right space only if it is clear of the mini-board grid.
            if mini and width > 85:
                return
            x = max(35, size * focus[2] + 8)
            y = 6
            if x + 32 >= width:
                return
        count = (
            self.episode_counts[self.selection] if self.selection < len(self.episode_counts) else 0
        )
        reasons = (
            self.death_reasons[self.selection] if self.selection < len(self.death_reasons) else {}
        )
        max_food = self.max_food[self.selection] if self.selection < len(self.max_food) else 0
        put(scr, y, x, "REPLAY ANALYTICS", curses.A_BOLD)
        put(
            scr,
            y + 1,
            x,
            f"{game_spec(getattr(self, 'game', 'snake')).score_label.title()} this game: {metric(env)}  Best: {max_food}",
        )
        put(
            scr,
            y + 2,
            x,
            f"Length: {len(env.body) if hasattr(env, 'body') else 1}  Steps without food: {getattr(env, 'steps_without_food', 0)}",
        )
        put(
            scr,
            y + 3,
            x,
            f"Finished episodes: {count}  Food events: {len(self.telemetry[self.selection])}",
        )
        if y + 5 < height - 2:
            put(scr, y + 4, x, "Ends: " + " ".join(f"{k}:{v}" for k, v in reasons.items() if v))
            put(
                scr,
                y + 5,
                x,
                "Food progress: "
                + self.sparkline(
                    [n for _, n in self.telemetry[self.selection]], min(25, width - x - 18)
                ),
            )
