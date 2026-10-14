from .core.checkpoints import safe_load
"""Textual frontend. Imported only when the optional tui extra is installed."""
import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import shutil
import time

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Log, Select, Static, TabbedContent, TabPane
from textual import on
from textual.reactive import reactive

from .dashboard import _command, _history, _latest_timing, _lines, _settings_defaults, _validate_settings, SETTINGS_FIELDS, _spark
from .games import game_spec, make_env
from .policy import Policy
from .preferences import load_preferences, save_preferences
from .service import RunService


class EvoForgeApp(App):
    TITLE = "EvoForge"
    SUB_TITLE = "Neuroevolution control center"
    CSS = """
    Screen { background: #101820; }
    Header { background: #15322c; color: #c0fbe5; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }
    .panel { border: round #39705f; padding: 1 2; margin-bottom: 1; height: auto; }
    .heading { color: #83e6bd; text-style: bold; margin: 0 0 1 0; }
    .actions { height: auto; margin: 1 0; }
    .actions Button { margin-right: 1; }
    .field { height: 3; margin-bottom: 1; }
    .field Label { width: 23; padding-top: 1; }
    .field Input, .field Select { width: 1fr; }
    #experiments { height: 1fr; }
    #logs { height: 1fr; border: round #39705f; }
    #board { height: 1fr; min-height: 14; color: #b7f7c9; overflow: auto; }
    #agent-board { height: 1fr; min-height: 12; color: #b7f7c9; overflow: auto; }
    #board.compact { height: 2fr; }
    #agent-board.compact { height: 1fr; }
    #board.expanded { height: 3fr; }
    #agent-board.expanded { height: 1fr; }
    #board.detail { height: 1fr; }
    #agent-board.detail { height: 3fr; }
    #resource { height: auto; }
    #metrics { height: auto; }
    #settings-scroll { height: 1fr; }
    #message { dock: bottom; height: 1; background: #244339; color: #f1f7f4; }
    """
    BINDINGS = [("ctrl+n", "new_experiment", "New run"), ("ctrl+r", "refresh", "Refresh"), ("ctrl+s", "save_settings", "Save settings"), ("ctrl+q", "quit_safe", "Quit")]
    directory = reactive(Path("runs/hybrid"))

    def __init__(self, directory="runs/hybrid"):
        super().__init__()
        self.directory = Path(directory).expanduser().resolve()
        self.runs_root = self.directory.parent
        self._last_saved_theme = None
        self._selected_experiment = None
        self.proc = None
        self.log_file = None
        self.paused = False
        self.replay_env = None
        self.replay_model = None
        self.replay_step = 0
        self.replay_seed = 900
        self.replay_locked = True
        self.replay_checkpoint_mtime = None
        self.last_log = ""
        self.agents = []
        self.selected_agent = 0
        self.spectator_multi = True
        self.replay_fps = 7
        self._last_replay_time = 0
        self._spectator_paused = set()
        self._spectator_stats = {}
        self.spectator_density = "compact"
        self.spectator_split = "balanced"
        self.spectator_show_all = True
        self._spectator_snapshot_mtime = None
        self.spectator_mode = 'live'
        self._frame_cursor = 0
        self._live_frames = {}
        self._closing = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="overview"):
            with TabPane("Overview", id="overview"):
                yield Static("TRAINING OVERVIEW", classes="heading")
                yield Static("", id="run-info", classes="panel")
                yield Static("", id="metrics", classes="panel")
                yield Static("", id="chart", classes="panel")
                yield Static("Resource monitoring unavailable", id="resource", classes="panel")
                with Horizontal(classes="actions"):
                    yield Button("Start / Resume", id="start", variant="success")
                    yield Button("Pause / Continue", id="pause")
                    yield Button("Stop", id="stop", variant="error")
                    yield Button("Extend +100", id="extend")
            with TabPane("Experiments", id="experiments-tab"):
                yield Static("EXPERIMENT LIBRARY", classes="heading")
                with Horizontal(classes="actions"):
                    yield Button("Refresh list", id="list-runs")
                    yield Button("Create run", id="new-run", variant="primary")
                    yield Input(placeholder="Run name / rename destination", id="new-name")
                yield DataTable(id="experiments", cursor_type="row")
                yield Static("Select a row and click Open; experiments are kept in separate directories.")
                with Horizontal(classes="actions"):
                    yield Button("Open selected", id="open-run", variant="success")
                    yield Button("Duplicate", id="duplicate-run")
                    yield Button("Rename", id="rename-run")
                    yield Button("Archive", id="archive-run")
            with TabPane("Spectator", id="spectator"):
                yield Static("LIVE TRAINING / CHAMPION / POPULATION", classes="heading")
                yield Select([('Live Training', 'live'), ('Champion Replay', 'champion'), ('Population Replay', 'population')],
                             id='spectator-mode', value='live', allow_blank=False)
                with Horizontal(classes="actions"):
                    yield Button("Load champion", id="load-champion", variant="primary")
                    yield Button("Restart episode", id="restart-replay")
                    yield Button("Pause selected", id="toggle-replay")
                    yield Button("Grid / Focus", id="grid-replay")
                    yield Button("Next agent", id="next-agent")
                    yield Button("Slower", id="slow-replay")
                    yield Button("Faster", id="fast-replay")
                    yield Button("Density", id="density-replay")
                    yield Button("Split", id="split-replay")
                    yield Button("Show all", id="all-replay")
                yield Static("No champion loaded.", id="board", classes="panel")
                yield Static("Selected agent: champion", id="agent-board", classes="panel")
                yield Static("Saved policy replays are independent of active training workers.", id="replay-note")
            with TabPane("Analytics", id="analytics"):
                yield Static("EXPERIMENT ANALYTICS", classes="heading")
                yield Static("", id="analytics-text", classes="panel")
                yield Static("", id="analytics-breakdown", classes="panel")
            with TabPane("Logs", id="logs-tab"):
                yield Static("TRAINING LOGS", classes="heading")
                yield Log(id="logs", highlight=False, auto_scroll=True)
            with TabPane("Settings", id="settings-tab"):
                yield Static("EXPERIMENT CONFIGURATION", classes="heading")
                yield Static("Choose a new run to edit settings; checkpointed settings are protected. Presets are starting points, not guarantees.")
                with Horizontal(classes="actions"):
                    yield Button("Quick Snake", id="preset-snake")
                    yield Button("Flappy Hybrid", id="preset-flappy")
                    yield Button("CPU Lite", id="preset-lite")
                yield Static("",id="settings-estimate",classes="panel")
                with VerticalScroll(id="settings-scroll"):
                    for key,label,kind,options in SETTINGS_FIELDS:
                        with Horizontal(classes="field"):
                            yield Label(label)
                            if kind == "choice":
                                yield Select([(s,s) for s in options], id=f"field-{key}", allow_blank=False)
                            else:
                                yield Input(id=f"field-{key}", type="integer")
                yield Button("Validate & Save", id="save-settings", variant="success")
        yield Static("Ready", id="message")
        yield Footer()

    def on_mount(self):
        prefs = load_preferences()
        if prefs.get("theme"):
            try: self.theme = prefs["theme"]
            except Exception: pass
        self._last_saved_theme = str(self.theme)
        self.query_one("#experiments", DataTable).add_columns("Name", "Game", "Mode", "Generation", "State")
        self._open_directory(self.directory)
        self.set_interval(0.8, self._refresh)
        self.set_interval(1 / 7, self._replay_tick)

    def notify_status(self, message):
        self.query_one("#message", Static).update(str(message))

    def _root(self):
        return self.runs_root

    def _open_directory(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.last_log = ""
        self.query_one("#logs", Log).clear()
        self._load_settings()
        self._list_runs()
        self._load_champion()
        self.spectator_mode = 'live'
        self._frame_cursor = 0
        self._live_frames = {}
        self._refresh()
        self.notify_status(f"Opened {self.directory}")

    def _list_runs(self):
        table = self.query_one("#experiments", DataTable)
        selected = self._selected_experiment
        table.clear()
        row_to_select = None
        for directory in sorted(self._root().iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                cfg = json.loads((directory / "config.json").read_text())
            except (OSError,ValueError):
                cfg = {}
            rows = _history(directory / "metrics.csv")
            generation = rows[-1].get("generation","—") if rows else "—"
            state = "Archived" if (directory / ".archived").exists() else "Checkpointed" if (directory / "checkpoint.pt").exists() else "New"
            table.add_row(directory.name, cfg.get("game","snake"),cfg.get("mode","hybrid"), str(generation),state, key=str(directory))
            if directory.resolve() == selected: row_to_select = table.row_count - 1
        if row_to_select is not None:
            table.move_cursor(row=row_to_select)

    def _load_settings(self):
        cfg = _settings_defaults()
        try:
            cfg.update(json.loads((self.directory/"config.json").read_text()))
        except (FileNotFoundError,ValueError,TypeError):
            pass
        for key,_,kind,_ in SETTINGS_FIELDS:
            control = self.query_one(f"#field-{key}")
            control.value = cfg[key] if kind == "choice" else str(cfg[key])

    def _read_settings(self):
        values = _settings_defaults()
        for key,_,kind,_ in SETTINGS_FIELDS:
            value = self.query_one(f"#field-{key}").value
            values[key] = str(value) if kind == "choice" else int(value)
        _validate_settings(values)
        return values

    def action_save_settings(self):
        if (self.directory/"checkpoint.pt").exists():
            self.notify_status("Checkpoint exists: create a fresh experiment to change settings.")
            return
        try:
            cfg = self._read_settings()
            target = self.directory/"config.json"
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg,indent=2))
            tmp.replace(target)
            self.notify_status("Configuration saved")
            self._list_runs()
        except (ValueError,TypeError,OSError) as exc:
            self.notify_status(f"Invalid settings: {exc}")

    def action_new_experiment(self):
        name = self.query_one("#new-name", Input).value.strip()
        if not name or name in (".","..") or "/" in name or "\\" in name or name.startswith("."):
            self.notify_status("Enter a simple run name (letters, numbers, - or _).")
            return
        if not all(c.isalnum() or c in "-_" for c in name):
            self.notify_status("Run names may contain only letters, numbers, - and _.")
            return
        path = self._root() / name
        if path.exists():
            self.notify_status("That run already exists; select it in the table.")
            return
        path.mkdir(parents=True)
        try:
            (path / "config.json").write_text(json.dumps(_settings_defaults(), indent=2))
        except OSError as exc:
            self.notify_status(f"Could not initialize run: {exc}")
            return
        self._selected_experiment = path.resolve()
        self._open_directory(path)
        self.query_one(TabbedContent).active = "settings-tab"
        self.notify_status(f"Created {name}; edit its configuration and save")

    def _refresh(self):
        if self._closing or not self.query("#run-info"):return
        if self.proc and self.proc.poll() is not None:
            rc = self.proc.returncode
            self.proc = None
            if self.log_file:
                self.log_file.close(); self.log_file = None
            self.notify_status(f"Training ended, exit code {rc}")
        cfg = {}
        try: cfg = json.loads((self.directory / "config.json").read_text())
        except (OSError,ValueError): pass
        rows = _history(self.directory/"metrics.csv")
        if self.spectator_mode == 'live':
            self._poll_frames()
        service_snapshot = RunService(self.directory).snapshot()
        latest = rows[-1] if rows else {}
        worker = service_snapshot["worker"]
        worker_state = worker.get("state", "idle")
        status = "Paused" if self.paused and self.proc else "Running" if self.proc else worker_state.title()
        self.query_one("#run-info", Static).update(f"RUN  {self.directory.name}    GAME  {cfg.get('game','snake')}    MODE  {cfg.get('mode','hybrid')}    STATUS  {status}")
        score_label = game_spec(cfg.get("game","snake")).score_label
        self.query_one("#metrics", Static).update(
            f"Generation: {latest.get('generation','—')} / {cfg.get('generations','—')}   "
            f"Best fitness: {latest.get('best_train','—')}   "
            f"Mean fitness: {latest.get('mean_train','—')}\n"
            f"Validation {score_label}: {latest.get('validation_food','—')}   "
            f"Hall of fame: {latest.get('hall_of_fame','—')}")
        def chart(field):
            try:return _spark([float(row[field]) for row in rows],52)
            except (ValueError,KeyError,TypeError):return "—"
        self.query_one("#chart",Static).update(f"Best    {chart('best_train')}\nAverage {chart('mean_train')}")
        self.query_one("#resource",Static).update(self._resources())
        timing = _latest_timing(self.directory)
        times = "" if not timing else f"\nLast generation: {timing.get('total_seconds','?')} seconds"
        self.query_one("#analytics-text",Static).update(f"Recorded generations: {len(rows)}\nBest fitness history: {chart('best_train')}\nMean fitness history: {chart('mean_train')}{times}")
        self.query_one("#analytics-breakdown",Static).update(self._analytics(rows))
        self._settings_estimate()
        current_theme = str(self.theme)
        if current_theme != self._last_saved_theme:
            try:
                save_preferences({"theme": current_theme})
                self._last_saved_theme = current_theme
            except OSError as exc:
                self.notify_status(f"Could not save theme preference: {exc}")
        log_path = self.directory / "training.log"
        lines = _lines(log_path,200)
        content = "\n".join(lines)
        if content != self.last_log:
            log = self.query_one("#logs", Log)
            log.clear()
            for line in lines: log.write_line(line)
            self.last_log = content

    def _load_champion(self, live=False):
        from .games import close_env
        from .agents import policy_for
        for agent in self.agents:
            close_env(agent['env'])
        self.spectator_mode = 'population' if live else 'champion'
        self.agents = []
        self._spectator_paused.clear()
        champion = self.directory / "champion.pt"
        snapshot = self.directory / "spectator.pt"
        if not champion.exists() and not snapshot.exists():
            self.query_one("#board",Static).update("Waiting for the trainer's first live policy snapshot…" if live else "No champion or live policy snapshot yet.")
            self.query_one("#agent-board",Static).update(""); return
        try:
            import torch
            from .viewer import load_champion
            if champion.exists():
                model, config = load_champion(champion); models = [model]
            else:
                models=[]; config={}
            if snapshot.exists() and live:
                data = safe_load(snapshot)
                snap_cfg=data.get("config",{})
                if not config: config=snap_cfg
                if all(snap_cfg.get(k,config.get(k)) == config.get(k) for k in ("game","size","hidden")):
                    for weights in data.get("policies",[])[:9]:
                        policy=policy_for(config.get("game","snake"), config["hidden"], config.get("game_config"), config["size"], config["max_steps"]);policy.load_state_dict(weights);policy.eval();models.append(policy)
            if not models: raise ValueError("no compatible policies in live snapshot")
            for i,policy in enumerate(models):
                env = make_env(config.get("game","snake"),config["size"],config["max_steps"], config.get("game_config"))
                obs = env.reset(self.replay_seed+i)
                self.agents.append({"env":env,"policy":policy,"obs":obs,"seed":self.replay_seed+i,"steps":0,"episodes":0,"last":""})
            self.selected_agent=0
            self._spectator_display()
            self.notify_status(f"Spectating {len(self.agents)} {'population replay' if live else 'champion replay'} policies; generation {data.get('generation','—') if snapshot.exists() and live else '—'}")
        except Exception as exc:
            self.query_one("#board",Static).update(f"Could not load spectator: {exc}")

    def _spectator_display(self):
        if self._closing or not self.agents or not self.query("#board"):
            return

        grid = self.query_one("#board", Static)
        detail = self.query_one("#agent-board", Static)
        for widget in (grid, detail):
            widget.remove_class("compact", "expanded", "detail")
            widget.add_class(self.spectator_split)

        def lines_for(i, dense=False):
            agent = self.agents[i]
            env = agent["env"]
            title = "CHAMPION" if i == 0 else f"AGENT {i}"
            title = ("> " if i == self.selected_agent else "  ") + title
            food = getattr(env, "food_eaten", None)
            if food is None:
                food = getattr(env, "score", 0)
            state = "PAUSED" if i in self._spectator_paused else "PLAYING"
            first = f"{title}  {state}  Score:{food}"
            second = f"Ep:{agent['episodes']+1}  Steps:{agent['steps']}  Seed:{agent['seed']}"
            body = str(env.render()).splitlines()
            if dense:
                return [first, second] + body
            tail = [f"Result: {agent['last'][:65]}"] if agent['last'] else []
            return [first, second] + body + tail

        def box(lines, width):
            inner = max(8, width - 4)
            return (["┌" + "─"*(inner+2) + "┐"] +
                    ["│ " + line[:inner].ljust(inner) + " │" for line in lines] +
                    ["└" + "─"*(inner+2) + "┘"])

        def compose_grid(cards, columns):
            chunks=[]
            for offset in range(0, len(cards), columns):
                row=cards[offset:offset+columns]
                height=max(map(len,row))
                widths=[len(r[0]) for r in row]
                chunks.extend("  ".join((r[y] if y<len(r) else " "*widths[j]) for j,r in enumerate(row)) for y in range(height))
                chunks.append("")
            return "\n".join(chunks).rstrip()

        visible = list(range(len(self.agents))) if self.spectator_show_all and self.spectator_multi else [self.selected_agent]
        width=max(40, self.size.width-10)
        render_width = max(len(line) for i in visible for line in lines_for(i, True)) + 4
        card_width = max(render_width, 23 if self.spectator_density == "compact" else 33)
        columns=max(1,width//(card_width+2))
        grid.update(compose_grid([box(lines_for(i, self.spectator_density == "compact"),card_width) for i in visible],columns))
        agent=self.agents[self.selected_agent]
        env=agent["env"]
        score=getattr(env,"food_eaten",getattr(env,"score",0))
        summary=(f"Selected: {'CHAMPION' if self.selected_agent == 0 else f'AGENT {self.selected_agent}'}"
                 f"  | Score: {score} | Episode: {agent['episodes']+1} | "
                 f"Step: {agent['steps']} | Speed: {self.replay_fps}/s\n"
                 f"Grid: {len(visible)}/{len(self.agents)} agents | Density: {self.spectator_density}"
                 f" | Split: {self.spectator_split} | Mode: {'grid' if self.spectator_multi else 'focus'}\n")
        detail.update(summary+"\n".join(lines_for(self.selected_agent)))

    def _replay_tick(self):
        if self._closing or self.spectator_mode == 'live':return
        if not self.agents or time.monotonic()-self._last_replay_time < 1/self.replay_fps:return
        self._last_replay_time=time.monotonic()
        for i,a in enumerate(self.agents):
            if i in self._spectator_paused:continue
            if getattr(a['env'],"done",False):
                a['episodes']+=1
                a['seed']+=101
                a['obs']=a['env'].reset(a['seed'])
                a['steps']=0
            else:
                a['obs'],_,done,info=a['env'].step(a['policy'].act(a['obs'],deterministic=True))
                a['steps']+=1
                if done: a['last']=str(info)
        self._spectator_display()

    def _poll_frames(self):
        from .telemetry import FrameChannel
        if not (self.directory/'telemetry.sqlite').exists():
            return
        try:
            frames = FrameChannel(self.directory).read(self._frame_cursor)
        except (OSError, __import__('sqlite3').OperationalError):
            return
        for event in frames:
            self._frame_cursor = event['seq']
            self._live_frames[event['agent']] = event
        if self._live_frames:
            panels = []
            for agent, event in sorted(self._live_frames.items()):
                panels.append(f"LIVE AGENT {agent} | Gen {event['generation']} | Step {event['step']} | Score {event['score']}\n" +
                              str(event['data'].get('text', event['data'])))
            self.query_one('#board', Static).update('\n\n'.join(panels))
            self.query_one('#replay-note', Static).update('Actual sampled evaluation frames; sequence gaps indicate sampling or dropped frames.')

    @on(Select.Changed, '#spectator-mode')
    def change_spectator_mode(self, event):
        self.spectator_mode = event.value
        if event.value == 'live':
            self._poll_frames()
        else:
            self._load_champion(live=event.value == 'population')

    def on_unmount(self):
        self._closing = True
        from .games import close_env
        for agent in self.agents:
            close_env(agent['env'])

    @on(DataTable.RowSelected, "#experiments")
    def _experiment_row_selected(self, event):
        self._selected_experiment = Path(str(event.row_key.value)).resolve()
        self.notify_status(f"Selected {self._selected_experiment.name}")

    def _selected_run(self):
        table = self.query_one("#experiments", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return self._selected_experiment if self._selected_experiment and self._selected_experiment.exists() else None
        name = str(table.get_row_at(table.cursor_row)[0])
        path = (self._root() / name).resolve()
        self._selected_experiment = path
        return path

    def _manage_run(self,kind):
        path=self._selected_run()
        if not path or not path.exists():return self.notify_status("Select an experiment first")
        if self.proc:return self.notify_status("Stop the trainer managed by this window first")
        name=self.query_one("#new-name",Input).value.strip()
        if kind in ("duplicate","rename"):
            if not name or not all(c.isalnum() or c in "-_" for c in name):
                return self.notify_status("Enter a new name using letters, numbers, - or _")
            target=self._root()/name
            if target.exists():return self.notify_status("Destination already exists")
            try:
                if kind=="duplicate":
                    target.mkdir()
                    original_config = path / "config.json"
                    if original_config.is_file():
                        shutil.copy2(original_config, target / "config.json")
                    else:
                        (target / "config.json").write_text(json.dumps(_settings_defaults(), indent=2))
                    # No checkpoint copied: an intentional new experiment using the same configuration.
                else:
                    current_selected = self.directory.resolve()==path.resolve()
                    path.rename(target)
                    if current_selected:self.directory=target
                self._selected_experiment = target.resolve()
                self._list_runs()
                self.notify_status(f"{kind.title()} successful: {target.name}")
            except OSError as exc:self.notify_status(f"{kind} failed: {exc}")
        else:
            marker=path/".archived"
            if marker.exists():marker.unlink()
            else:marker.write_text("Archived by EvoForge Textual\n")
            self._list_runs()
            self.notify_status(f"Archive state updated for {path.name}")

    def _resources(self):
        try:
            import os
            load=", ".join(f"{x:.2f}" for x in os.getloadavg())
            mem=""
            if Path("/proc/meminfo").exists():
                values={}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    k,_,v=line.partition(":")
                    if k in ("MemTotal","MemAvailable"):values[k]=int(v.strip().split()[0])
                if len(values)==2:mem=f" | RAM available: {values['MemAvailable']/1024**2:.1f} / {values['MemTotal']/1024**2:.1f} GiB"
            gpu=""
            try:
                result=subprocess.run(["nvidia-smi","--query-gpu=utilization.gpu,memory.used,memory.total","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=0.4)
                if result.returncode==0:gpu=" | GPU: "+result.stdout.strip().splitlines()[0]
            except (OSError,subprocess.TimeoutExpired,IndexError):pass
            return f"System load (1/5/15 min): {load}{mem}{gpu}"
        except (OSError,ValueError):return "System resource information unavailable"

    def _analytics(self,rows):
        if not rows:return "No training metrics yet."
        last=rows[-1]
        interesting=["best_food","mean_food","validation_food","ppo_refinements","ppo_updates","environment_steps"]
        return "LATEST TRAINING METRICS\n"+"\n".join(f"{key.replace('_',' ').title()}: {last[key]}" for key in interesting if key in last)

    def _settings_estimate(self):
        try:
            settings=self._read_settings()
            interactions=settings['population']*settings['eval_episodes']*settings['max_steps']*settings['generations']
            self.query_one("#settings-estimate",Static).update(f"Upper-bound evaluation steps: {interactions:,} (excludes PPO; most episodes end early)")
        except (ValueError,TypeError,KeyError):pass

    def _preset(self,kind):
        if (self.directory/"checkpoint.pt").exists():return self.notify_status("Checkpointed experiment: create a new run for presets")
        cfg=_settings_defaults()
        cfg.update({"game":"flappy"} if kind=="flappy" else {"population":12,"generations":30,"ppo_candidates":2,"eval_episodes":2} if kind=="lite" else {"game":"snake","population":64,"generations":200,"ppo_candidates":8})
        for key,_,type_,_ in SETTINGS_FIELDS:
            self.query_one(f"#field-{key}").value=cfg[key] if type_=="choice" else str(cfg[key])
        self._settings_estimate()
        self.notify_status(f"{kind} preset applied; save before training")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed):
        key = event.button.id
        if key == "new-run": self.action_new_experiment()
        elif key == "list-runs": self._list_runs()
        elif key == "open-run":
            table = self.query_one("#experiments",DataTable)
            if table.cursor_row is None or table.row_count == 0:return
            selected = self._selected_run()
            if selected is None:
                self.notify_status("Select an experiment first"); return
            if self.proc:
                self.notify_status("Stop the trainer managed by this window before switching.");return
            self._open_directory(selected)
        elif key == "save-settings": self.action_save_settings()
        elif key == "start": self.start_training()
        elif key == "pause": self.pause_training()
        elif key == "stop": self.stop_training()
        elif key == "extend": self.extend_training()
        elif key == "load-champion": self._load_champion()
        elif key in ("duplicate-run","rename-run","archive-run"):self._manage_run(key.split("-")[0])
        elif key == "grid-replay":self.spectator_multi=not self.spectator_multi;self._spectator_display()
        elif key == "density-replay":
            self.spectator_density = "spacious" if self.spectator_density == "compact" else "compact"
            self._spectator_display()
        elif key == "split-replay":
            choices = ("balanced", "expanded", "detail")
            self.spectator_split = choices[(choices.index(self.spectator_split)+1)%len(choices)]
            self._spectator_display()
        elif key == "all-replay":
            self.spectator_show_all = not self.spectator_show_all
            self._spectator_display()
        elif key == "next-agent":self.selected_agent=(self.selected_agent+1)%max(1,len(self.agents));self._spectator_display()
        elif key == "slow-replay":self.replay_fps=max(1,self.replay_fps-1)
        elif key == "fast-replay":self.replay_fps=min(30,self.replay_fps+1)
        elif key.startswith("preset-"):self._preset(key[7:])
        elif key == "toggle-replay":
            if self.selected_agent in self._spectator_paused:self._spectator_paused.remove(self.selected_agent)
            else:self._spectator_paused.add(self.selected_agent)
        elif key == "restart-replay":
            if self.agents:
                a=self.agents[self.selected_agent]
                a["seed"]+=100
                a["obs"]=a["env"].reset(a["seed"])
                a["steps"]=0
                self._spectator_display()

    def start_training(self):
        if self.proc:
            self.notify_status("Training already running in this window");return
        if (self.directory/".archived").exists():return self.notify_status("Unarchive this experiment before training")
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            self.log_file = (self.directory/"training.log").open("a", buffering=1)
            cmd = _command(self.directory,(self.directory/"checkpoint.pt").exists())
            self.log_file.write("\n=== " + " ".join(cmd) + " ===\n")
            self.proc = subprocess.Popen(cmd,stdout=self.log_file,stderr=subprocess.STDOUT,start_new_session=True)
            self.paused = False
            self.notify_status(f"Started training PID {self.proc.pid}")
        except Exception as exc:
            self.notify_status(f"Start failed: {exc}")
            if self.log_file: self.log_file.close(); self.log_file=None

    def pause_training(self):
        if not self.proc:
            self.notify_status("No trainer managed by this window");return
        if os.name != "posix":return
        self.paused = not self.paused
        self.proc.send_signal(signal.SIGSTOP if self.paused else signal.SIGCONT)
        self.notify_status("Paused" if self.paused else "Resumed")

    def stop_training(self):
        if not self.proc:return
        if self.paused:self.proc.send_signal(signal.SIGCONT)
        self.proc.terminate()
        self.notify_status("Stop requested; checkpoint will be from last completed generation")

    def extend_training(self):
        if self.proc:
            self.notify_status("Stop training before extending");return
        path = self.directory/"checkpoint.pt"
        if not path.exists():
            self.notify_status("No checkpoint to extend");return
        try:
            import torch
            data = safe_load(path)
            cfg = dict(data["config"])
            cfg["generations"] = max(int(cfg["generations"]),int(data["generation"])) + 100
            (self.directory/"config.json").write_text(json.dumps(cfg,indent=2))
            self._load_settings()
            self.notify_status(f"Extended target to {cfg['generations']} generations")
        except Exception as exc:self.notify_status(f"Extension failed: {exc}")

    def action_refresh(self): self._refresh(); self._list_runs()

    def action_quit_safe(self):
        if self.proc:
            self.notify_status("Stop the trainer before quitting, or detach with Ctrl+C in a separate shell.")
            return
        self.exit()


def main(directory="runs/hybrid"):
    EvoForgeApp(directory).run()
