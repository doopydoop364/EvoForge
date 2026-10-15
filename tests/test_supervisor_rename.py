"""A trained run retains its files and relational metadata across renames."""

import sqlite3

import pytest

from evoforge.supervisor import Supervisor
from evoforge.trainer import Config


@pytest.mark.parametrize("reject_update", [False, True])
def test_rename_trained_run_is_transactional(tmp_path, reject_update):
    manager = Supervisor(tmp_path)
    manager.create("trained", Config())
    checkpoint = manager.path("trained") / "checkpoint.pt"
    checkpoint.write_bytes(b"preserve checkpoint")
    manager.database.sync_metrics("trained", [{"generation": 0, "best_train": 12}])
    with manager.database.connect() as db:
        db.execute("UPDATE experiments SET status='COMPLETED' WHERE id='trained'")
        db.execute(
            "INSERT INTO workers(experiment,identity,heartbeat,generation) VALUES(?,?,?,?)",
            ("trained", "finished-worker", 0, 1),
        )
        if reject_update:
            db.execute(
                "CREATE TRIGGER reject_rename BEFORE UPDATE ON metrics "
                "BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END"
            )
    if reject_update:
        with pytest.raises(sqlite3.IntegrityError, match="injected storage failure"):
            manager.rename("trained", "renamed")
        surviving, absent = "trained", "renamed"
    else:
        manager.rename("trained", "renamed")
        surviving, absent = "renamed", "trained"
    assert not manager.path(absent).exists()
    assert (manager.path(surviving) / "checkpoint.pt").read_bytes() == b"preserve checkpoint"
    row = manager.inspect(surviving)
    assert row["status"] == "COMPLETED"
    assert row["worker"]["identity"] == "finished-worker"
    assert row["worker"]["generation"] == 1
    with manager.database.connect() as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT id FROM experiments").fetchone()[0] == surviving
        assert db.execute("SELECT experiment FROM metrics").fetchone()[0] == surviving
        assert {r[0] for r in db.execute("SELECT experiment FROM events")} == {surviving}
