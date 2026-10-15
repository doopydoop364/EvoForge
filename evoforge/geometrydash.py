"""EvoForge auto-run Geometry Dash-inspired eight-mode simulation.

Independent training simulator, NOT the original game's physics engine.
Action 0=release, 1=short click, 2=hold. A click is one frame of input;
repeated action 1 means consecutive short clicks (distinct taps). The level
scrolls automatically; platformer controls are intentionally not implemented.
"""

from __future__ import annotations

import os

import numpy as np

MODES = ("cube", "ship", "ball", "ufo", "wave", "robot", "spider", "swing")
# Gameplay objects documented in the 2.2 editor. These are simplified physical
# equivalents; visual-only triggers are recorded as state, not rendered as shaders.
SPEEDS = {"slow": 0.8, "normal": 1.0, "fast": 1.2, "faster": 1.4, "very_fast": 1.6}
PORTAL_TYPES = (
    "cube",
    "ship",
    "ball",
    "ufo",
    "wave",
    "robot",
    "spider",
    "swing",
    "gravity_normal",
    "gravity_reverse",
    "gravity_flip",
    "mini",
    "normal_size",
    "dual_on",
    "dual_off",
    "mirror_on",
    "mirror_off",
    "teleport",
    "speed_slow",
    "speed_normal",
    "speed_fast",
    "speed_faster",
    "speed_very_fast",
)
PAD_TYPES = ("yellow", "pink", "red", "blue", "spider")
ORB_TYPES = (
    "yellow",
    "pink",
    "red",
    "blue",
    "green",
    "black",
    "spider",
    "dash_green",
    "dash_pink",
    "teleport",
    "custom",
)
# Physical gameplay modifiers only. See README for trigger limitations.
TRIGGER_TYPES = (
    "reverse",
    "gameplay_forward",
    "gameplay_reverse",
    "gravity_normal",
    "gravity_reverse",
    "timewarp",
    "end",
    "camera_zoom",
    "camera_rotate",
    "camera_offset",
    "camera_static",
    "camera_mode",
)
SYMBOLS = {
    "cube": "C",
    "ship": ">",
    "ball": "O",
    "ufo": "U",
    "wave": "W",
    "robot": "R",
    "spider": "S",
    "swing": "G",
}


# Standard 24-bit ANSI escape sequences. Only emitted on explicit request,
# preserving the fixed-width plain-text API expected by EvoForge tests.
COLORS = {
    "player": "38;2;80;220;255",
    "dead": "1;38;2;255;80;80",
    "hazard": "1;38;2;255;92;92",
    "ground": "38;2;148;158;175",
    "ceiling": "38;2;148;158;175",
    "orb": "1;38;2;255;218;91",
    "pad": "1;38;2;104;240;152",
    "portal": "1;38;2;172;128;255",
    "trigger": "1;38;2;255;166;92",
    "background": "38;2;90;101;118",
}
LEGEND = (
    "PLAYER: C Cube, > Ship, O Ball, U UFO, W Wave, R Robot, "
    "S Spider, G Swing, X collision\n"
    "WORLD: ^ ground spike/block, v ceiling spike, _ gap (shown as blank), "
    ". floor, # ground support, - ceiling\n"
    "OBJECTS: o orb, = jump pad, | portal (mode/gravity/speed/size/etc.), "
    "! trigger, space empty\n"
    "COLORS: cyan player, red hazard/death, yellow orb, green pad, "
    "purple portal, orange trigger, gray terrain"
)


def _paint(character, kind):
    return f"\x1b[{COLORS[kind]}m{character}\x1b[0m"


class GeometryDash:
    observation_size = 17
    action_size = 3
    score_label = "tiles cleared"

    def __init__(self, size=10, max_steps=300, mode=None):
        if size < 7 or max_steps < 1:
            raise ValueError("size >= 7 and max_steps >= 1 are required")
        if mode is not None and mode not in MODES:
            raise ValueError(f"mode must be one of: {', '.join(MODES)}")
        self.size = size
        self.max_steps = max_steps
        self.fixed_mode = mode
        self.reset()

    def reset(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.length = max(40, min(self.max_steps, self.size * 24))
        self.hazards = {}
        self.imported_level = None
        self.import_report = None
        self.portals = {}
        self.pads = {}
        self.orbs = {}
        self.triggers = {}
        self.speed = "normal"
        self.mini = False
        self.dual = False
        self.mirror = False
        self.direction = 1
        self.camera = {"zoom": 1.0, "rotate": 0.0, "offset": 0.0, "static": False, "free": False}
        self.timewarp = 1.0
        self.dash_frames = 0
        self.active_objects = set()
        self.events = []
        # Long enough sections that each mode has meaningful training examples.
        # Portal 0 is implicit; the first eight segments visit all modes on long runs.
        sequence = [MODES[0]] + list(self.rng.permutation(MODES[1:]))
        self.mode = self.fixed_mode or sequence[0]
        if self.fixed_mode is None:
            for index, x in enumerate(range(22, self.length - 9, 22), start=1):
                self.portals[x] = sequence[index % len(sequence)]
        # Sparse obstacles with generous spacing (not official GD levels).
        x = 9
        while x < self.length - 7:
            kind = self.rng.choice(("spike", "gap", "ceiling_spike"))
            if kind == "spike":
                self.hazards[x] = "^"
            elif kind == "gap":
                self.hazards[x] = "_"
            else:
                self.hazards[x] = "v"
            x += int(self.rng.integers(9, 14))
        # Optional real level import. Set once for CLI/TUI worker processes.
        source = os.environ.get("EVOFORGE_GMD_LEVEL")
        if source:
            from .gmd_import import load_level

            imported = load_level(source)
            self.hazards = imported.hazards.copy()
            self.portals = imported.portals.copy()
            self.pads = imported.pads.copy()
            self.orbs = imported.orbs.copy()
            self.triggers = {}
            self.length = imported.length
            self.import_report = imported.report()
            self.imported_level = imported
        self.x = 0.0
        self.y = (self.size - 2) / 2 if self.mode in ("ship", "ufo", "wave", "swing") else 0.0
        self.vy = 0.0
        self.gravity = -1  # -1 toward floor, +1 toward ceiling
        self.grounded = True
        self.steps = self.score = self.food_eaten = self.steps_without_food = 0
        self.done = self.completed = self.collision = False
        self.held = False
        self.robot_hold = 0
        self.visited = {(0, 0)}
        return self.observe()

    def _surface(self):
        return 0.0 if self.gravity == -1 else float(self.size - 2)

    def _obstacle_at(self, column):
        return self.hazards.get(column, ".")

    def observe(self):
        ahead = [self._obstacle_at(int(self.x) + d) for d in range(1, 6)]
        return np.asarray(
            [
                self.y / (self.size - 2),
                np.clip(self.vy / 3.0, -1.0, 1.0),
                float(self.grounded),
                float(self.gravity == 1),
                float(self.held),
                *[float(t in ("^", "_")) for t in ahead],
                *[float(t == "v") for t in ahead],
                self.x / self.length,
                MODES.index(self.mode) / (len(MODES) - 1),
            ],
            dtype=np.float32,
        )

    def _change_mode(self, mode):
        self.mode = mode
        if mode in ("ship", "ufo", "wave", "swing") and (self.y < 0.2 or self.y > self.size - 2.2):
            self.y = (self.size - 2) / 2
        self.robot_hold = 0
        self.vy = 0.0
        if mode in ("cube", "robot", "ball", "spider"):
            self.grounded = abs(self.y - self._surface()) < 0.1
        else:
            self.grounded = False

    def _apply_portal(self, portal):
        """Apply a portal name, dict with type/target, or legacy mode string."""
        if isinstance(portal, dict):
            kind = portal.get("type", "")
            target = portal.get("target")
        else:
            kind, target = portal, None
        if kind in MODES:
            self._change_mode(kind)
        elif kind.startswith("speed_"):
            speed = kind[6:]
            if speed not in SPEEDS:
                raise ValueError(f"unknown speed: {speed}")
            self.speed = speed
        elif kind in ("gravity_normal", "gravity_reverse", "gravity_flip"):
            self.gravity = (
                -1
                if kind == "gravity_normal"
                else 1
                if kind == "gravity_reverse"
                else -self.gravity
            )
            self.grounded = False
        elif kind in ("mini", "normal_size"):
            self.mini = kind == "mini"
        elif kind in ("dual_on", "dual_off"):
            # Dual visual/state flag only: no second independently simulated icon.
            self.dual = kind == "dual_on"
        elif kind in ("mirror_on", "mirror_off"):
            # Mirrors the camera image, not the physical running direction.
            self.mirror = kind == "mirror_on"
        elif kind == "teleport":
            if target is None:
                raise ValueError("teleport portal requires target coordinate")
            self.y = float(np.clip(target, 0, self.size - 2))
            self.vy = 0.0
        else:
            raise ValueError(f"unknown portal: {kind}")
        self.events.append(("portal", kind))

    def _spider_teleport(self):
        self.gravity *= -1
        self.y = self._surface()
        self.vy = 0.0
        self.grounded = True

    def _apply_transporter(self, kind, orb=False):
        if kind not in (ORB_TYPES if orb else PAD_TYPES):
            raise ValueError(f"unknown {'orb' if orb else 'pad'}: {kind}")
        if kind in ("yellow", "pink", "red") and self.mode != "wave":
            strength = {"pink": 1.3, "yellow": 2.1, "red": 2.8}[kind]
            self.vy = -self.gravity * strength
            self.grounded = False
        elif kind == "blue":
            self.gravity *= -1
            if self.mode != "wave":
                self.vy = -self.gravity * 1.7
            self.grounded = False
        elif kind == "green":
            self.gravity *= -1
            self.vy = -self.gravity * 2.1
            self.grounded = False
        elif kind == "black":
            self.vy = self.gravity * 3.0
            self.grounded = False
        elif kind == "spider":
            self._spider_teleport()
        elif kind in ("dash_green", "dash_pink"):
            if kind == "dash_pink":
                self.gravity *= -1
            self.dash_frames = 5
            self.vy = -self.gravity * 0.45
            self.grounded = False
        # Custom orb requires a separately programmed trigger; inert by default.
        self.events.append(("orb" if orb else "pad", kind))

    def _apply_trigger(self, entry):
        if isinstance(entry, str):
            kind, value = entry, None
        else:
            kind, value = entry.get("type"), entry.get("value")
        if kind not in TRIGGER_TYPES:
            raise ValueError(f"unknown trigger: {kind}")
        if kind in ("reverse", "gameplay_reverse"):
            self.direction = -self.direction if kind == "reverse" else -1
        elif kind == "gameplay_forward":
            self.direction = 1
        elif kind in ("gravity_normal", "gravity_reverse"):
            self.gravity = -1 if kind == "gravity_normal" else 1
        elif kind == "timewarp":
            if value is None or not (0.2 <= float(value) <= 3):
                raise ValueError("timewarp value must be in [0.2, 3]")
            self.timewarp = float(value)
        elif kind == "end":
            self.completed = True
        elif kind.startswith("camera_"):
            key = kind[7:]
            self.camera[key] = value if value is not None else (not self.camera.get(key, False))
        self.events.append(("trigger", kind))

    def _activate_objects(self, column, pressed):
        # At most one activation per object crossing, including reverse passages.
        if column in self.portals and ("portal", column) not in self.active_objects:
            self.active_objects.add(("portal", column))
            self._apply_portal(self.portals[column])
        if column in self.triggers and ("trigger", column) not in self.active_objects:
            self.active_objects.add(("trigger", column))
            entries = self.triggers[column]
            for entry in entries if isinstance(entries, list) else [entries]:
                self._apply_trigger(entry)
        if column in self.pads and ("pad", column) not in self.active_objects:
            self.active_objects.add(("pad", column))
            self._apply_transporter(self.pads[column])
        # Orbs only activate on input press, when within the current column.
        if pressed and column in self.orbs and ("orb", column) not in self.active_objects:
            self.active_objects.add(("orb", column))
            self._apply_transporter(self.orbs[column], orb=True)

    def _tap_or_hold(self, action):
        # One-frame clicks can be repeated; hold only creates a new press at entry.
        hold = action == 2
        pressed = action == 1 or (hold and not self.held)
        self.held = hold
        return pressed, action != 0

    def _motion(self, pressed, active, dt):
        g = 0.47 * self.gravity
        if self.mode == "cube":
            if active and self.grounded:
                self.vy = -self.gravity * 2.15
                self.grounded = False
            self.vy += g * dt
        elif self.mode == "robot":
            if pressed and self.grounded:
                self.vy = -self.gravity * 1.45
                self.robot_hold = 0
                self.grounded = False
            if active and not self.grounded and self.robot_hold < 4:
                self.vy += -self.gravity * 0.27 * dt
                self.robot_hold += dt
            self.vy += g * dt
        elif self.mode == "ship":
            self.vy += (-self.gravity * 0.36 if active else g * 0.55) * dt
            self.vy = float(np.clip(self.vy, -1.35, 1.35))
        elif self.mode == "ball":
            if pressed and self.grounded:
                self.gravity *= -1
                self.grounded = False
                self.vy = 0.0
            self.vy += 0.47 * self.gravity * dt
        elif self.mode == "ufo":
            if pressed:
                self.vy = -self.gravity * 1.48
            self.vy += g * 0.62 * dt
        elif self.mode == "wave":
            self.vy = (1.0 if active else -1.0) * (-self.gravity)
        elif self.mode == "spider":
            if pressed and self.grounded:
                self.gravity *= -1
                self.y = self._surface()
                self.vy = 0.0
                self.grounded = True
                return
            self.vy += 0.47 * self.gravity * dt
        elif self.mode == "swing":
            if pressed:
                self.gravity *= -1
            self.vy += 0.32 * self.gravity * dt
            self.vy = float(np.clip(self.vy, -1.4, 1.4))
        if self.dash_frames > 0:
            self.vy = -self.gravity * 0.45
        self.y += self.vy * dt
        # Ground and ceiling contact: for wave/ship/UFO/swing, they are hazards.
        top = float(self.size - 2)
        if self.y <= 0:
            if self.mode in ("wave", "ship", "ufo", "swing"):
                self.collision = True
            self.y = 0.0
            if self.gravity == -1:
                self.grounded = True
                self.vy = 0
            elif self.mode in ("ball", "spider"):
                self.collision = True
        elif self.y >= top:
            if self.mode in ("wave", "ship", "ufo", "swing"):
                self.collision = True
            self.y = top
            if self.gravity == 1:
                self.grounded = True
                self.vy = 0
            elif self.mode in ("ball", "spider"):
                self.collision = True
        else:
            self.grounded = False

    def _check_hazard(self):
        block = self._obstacle_at(int(self.x + 0.00001))
        if block == "^" and self.y < 0.85:
            self.collision = True
        elif block == "v" and self.y > self.size - 2.85:
            self.collision = True
        elif block == "_" and self.y < 0.26 and self.gravity == -1:
            self.collision = True

    def step(self, action):
        if self.done:
            raise RuntimeError("reset after terminal state")
        if int(action) not in (0, 1, 2):
            raise ValueError("action must be 0, 1, or 2")
        pressed, active = self._tap_or_hold(int(action))
        self.steps += 1
        # Substeps reduce tunnelling through floors and hazards.
        self.events = []
        # Start-of-step objects support orbs placed at the player's coordinate.
        self._activate_objects(int(self.x), pressed)
        for sub in range(8):
            if self.completed:
                break
            delta = 0.125 * SPEEDS[self.speed] * self.timewarp
            old_x = self.x
            self.x = max(0.0, self.x + self.direction * delta)
            # Check all crossed integer columns, including faster speeds.
            lo, hi = sorted((int(old_x), int(self.x)))
            for col in range(lo, hi + 1):
                if col == int(old_x) and col != int(self.x):
                    continue
                self._activate_objects(col, pressed and sub == 0)
            self._motion(pressed and sub == 0, active, 0.125)
            self._check_hazard()
            if self.collision:
                break
        self.dash_frames = max(0, self.dash_frames - 1)
        self.completed = self.completed or (not self.collision and self.x >= self.length)
        self.done = self.collision or self.completed or self.steps >= self.max_steps
        if not self.collision:
            self.score = max(self.score, min(self.length, int(self.x)))
            self.food_eaten = self.score
            self.visited.add((int(self.x), int(round(self.y))))
        reward = -1.0 if self.collision else 1.0 / self.length
        if self.completed:
            reward += 3.0
        return (
            self.observe(),
            reward,
            self.done,
            {
                "score": self.score,
                "food": self.score,
                "steps": self.steps,
                "progress": min(1.0, self.score / self.length),
                "completed": self.completed,
                "collision": self.collision,
                "mode": self.mode,
                "gravity": self.gravity,
                "speed": self.speed,
                "mini": self.mini,
                "dual": self.dual,
                "mirror": self.mirror,
                "direction": self.direction,
                "events": list(self.events),
            },
        )

    @staticmethod
    def legend():
        """Explain all ASCII symbols in the stable terminal board."""
        return LEGEND

    def render_scene(self):
        """Capture presentation without advancing physics or consuming RNG."""
        from .rendering.geometrydash import scene

        return scene(self)

    def render(self, color=False, legend=False):
        left = max(0, int(self.x) - 2)
        player_col = int(self.x) - left
        player_row = self.size - 2 - int(round(self.y))
        rows = []
        for row in range(self.size):
            line = []
            for col in range(self.size):
                x = left + col
                hazard = self._obstacle_at(x)
                if (row, col) == (player_row, player_col):
                    ch = "X" if self.collision else SYMBOLS[self.mode]
                elif row == self.size - 2:
                    ch = "^" if hazard == "^" else (" " if hazard == "_" else ".")
                elif row == 0:
                    ch = "v" if hazard == "v" else "-"
                elif row == self.size - 1:
                    ch = " " if hazard == "_" else "#"
                elif x in self.orbs and row == self.size // 2:
                    ch = "o"
                elif x in self.pads and row == self.size - 3:
                    ch = "="
                elif x in self.triggers and row == self.size // 2:
                    ch = "!"
                elif x in self.portals and row == self.size // 2:
                    ch = "|"
                else:
                    ch = " "
                if color and ch != " ":
                    if (row, col) == (player_row, player_col):
                        kind = "dead" if self.collision else "player"
                    elif ch in ("^", "v"):
                        kind = "hazard"
                    else:
                        kind = {
                            "o": "orb",
                            "=": "pad",
                            "|": "portal",
                            "!": "trigger",
                            "#": "ground",
                            ".": "ground",
                            "-": "ceiling",
                        }.get(ch, "background")
                    line.append(_paint(ch, kind))
                else:
                    line.append(ch)
            rows.append("".join(line))
        board = "\n".join(rows)
        return board + ("\n\n" + self.legend() if legend else "")
