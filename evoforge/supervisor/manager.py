"""Durable local supervisor. Clients submit requests, workers own advisory locks."""
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from evoforge.core.checkpoints import atomic_json
from evoforge.games import game_version
from evoforge.storage import Database
from .lifecycle import ACTIVE, incarnation, transition


class WorkerConflict(ValueError):
    pass


class Supervisor:
    def __init__(self, root='runs'):
        self.database = Database(root)
        self.root = self.database.root
        self.children = {}

    def path(self, experiment):
        if not isinstance(experiment, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', experiment):
            raise ValueError('Experiment id must be 1-80 letters, numbers, underscores or hyphens')
        path = self.root / experiment
        if path.resolve().parent != self.root or path.is_symlink():
            raise ValueError('Experiment path must stay inside storage root')
        return path

    def create(self, experiment, config):
        from evoforge.trainer import Config
        cfg = config if isinstance(config, Config) else Config(**config)
        cfg.validate()
        path = self.path(experiment)
        try:
            path.mkdir()
        except FileExistsError as exc:
            raise WorkerConflict('Experiment already exists') from exc
        atomic_json(path / 'config.json', asdict(cfg))
        self.register(experiment)
        return self.inspect(experiment)

    def register(self, experiment):
        path = self.path(experiment)
        cfg = json.loads((path / 'config.json').read_text())
        now = time.time()
        with self.database.connect() as db:
            db.execute('INSERT OR IGNORE INTO experiments(id,config,status,created,updated,game_version) VALUES(?,?,?,?,?,?)',
                       (experiment, json.dumps(cfg), 'CREATED', now, now, game_version(cfg.get('game', 'snake'))))
        return path

    def list(self):
        for path in self.root.iterdir():
            if path.is_dir() and not path.is_symlink() and (path / 'config.json').exists():
                try:
                    self.register(path.name)
                except (ValueError, OSError):
                    continue
        with self.database.connect() as db:
            ids = [r['id'] for r in db.execute('SELECT id FROM experiments ORDER BY created')]
        return [self.inspect(name) for name in ids]

    def inspect(self, experiment):
        self.path(experiment)
        with self.database.connect() as db:
            row = db.execute('SELECT * FROM experiments WHERE id=?', (experiment,)).fetchone()
            if not row:
                raise KeyError(experiment)
            worker = db.execute('SELECT * FROM workers WHERE experiment=?', (experiment,)).fetchone()
            row = dict(row)
            if worker:
                worker = dict(worker)
                if row['status'] in ACTIVE:
                    alive = worker['incarnation'] and incarnation(worker['pid']) == worker['incarnation']
                    stale = time.time()-worker['heartbeat'] > 15
                    # While the parent is publishing process identity allow startup grace.
                    if (not alive and time.time()-worker['heartbeat'] > 3) or stale:
                        reason = 'Worker identity no longer exists' if not alive else 'Worker heartbeat stale'
                        transition(db, experiment, 'FAILED')
                        db.execute('UPDATE workers SET error=? WHERE experiment=?', (reason, experiment))
                        row['status'], worker['error'] = 'FAILED', reason
            row['config'] = json.loads(row['config'])
            row['worker'] = worker
        child = self.children.get(experiment)
        if child and child.poll() is not None:
            self.children.pop(experiment, None)
        return row

    def _claim(self, experiment, fd):
        row = self.inspect(experiment)
        if row['archived'] or (self.path(experiment) / '.archived').exists():
            raise WorkerConflict('Unarchive experiment before starting')
        identity = uuid.uuid4().hex
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = db.execute('SELECT status FROM experiments WHERE id=?', (experiment,)).fetchone()['status']
            if state in ACTIVE:
                raise WorkerConflict('Experiment already has an active worker')
            if state in ('STOPPED', 'COMPLETED', 'FAILED') and (self.path(experiment) / 'checkpoint.pt').exists():
                transition(db, experiment, 'RECOVERING')
            transition(db, experiment, 'QUEUED')
            db.execute('INSERT OR REPLACE INTO workers(experiment,identity,heartbeat,generation) VALUES(?,?,?,?)',
                       (experiment, identity, time.time(), row.get('worker', {}).get('generation', 0) if row.get('worker') else 0))
            transition(db, experiment, 'STARTING')
        return identity

    def start(self, experiment):
        path = self.register(experiment)
        fd = os.open(path / '.worker.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkerConflict('Experiment already has a worker lock') from exc
            identity = self._claim(experiment, fd)
            try:
                with (path / 'training.log').open('a') as log:
                    child = subprocess.Popen([sys.executable, '-m', 'evoforge.supervisor.worker',
                        '--root', str(self.root), '--experiment', experiment, '--identity', identity, '--lock-fd', str(fd)],
                        pass_fds=(fd,), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True, close_fds=True)
                self.children[experiment] = child
                with self.database.connect() as db:
                    db.execute('UPDATE workers SET pid=?,incarnation=? WHERE experiment=? AND identity=?',
                               (child.pid, incarnation(child.pid), experiment, identity))
            except Exception:
                with self.database.connect() as db:
                    transition(db, experiment, 'FAILED')
                raise
        finally:
            os.close(fd)
        return self.inspect(experiment)

    def request(self, experiment, action):
        row = self.inspect(experiment)
        expected = {'pause': {'RUNNING'}, 'resume': {'PAUSED'}, 'stop': {'RUNNING', 'PAUSED', 'STARTING'}}
        if action not in expected:
            raise ValueError('Unknown worker action')
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT status FROM experiments WHERE id=?', (experiment,)).fetchone()['status']
            if current not in expected[action]:
                raise WorkerConflict(f'Cannot {action} worker in state {current}')
            pending = db.execute('SELECT request FROM workers WHERE experiment=?', (experiment,)).fetchone()['request']
            if pending and pending != action:
                raise WorkerConflict(f'Worker already has pending {pending} request')
            db.execute('UPDATE workers SET request=? WHERE experiment=?', (action, experiment))
            self.database.event(db, experiment, 'request', {'action': action})
        return self.inspect(experiment)

    def workers(self):
        return [row for row in self.list() if row['worker']]
