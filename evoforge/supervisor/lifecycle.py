"""Persisted job states and process incarnation identity (Linux primary platform)."""

from pathlib import Path

TRANSITIONS = {
    "CREATED": {"QUEUED"},
    "QUEUED": {"STARTING", "FAILED", "STOPPED"},
    "STARTING": {"RUNNING", "STOPPING", "FAILED"},
    "RUNNING": {"PAUSED", "STOPPING", "COMPLETED", "FAILED"},
    "PAUSED": {"RUNNING", "STOPPING", "FAILED"},
    "STOPPING": {"STOPPED", "FAILED"},
    "STOPPED": {"RECOVERING", "QUEUED"},
    "COMPLETED": {"RECOVERING"},
    "FAILED": {"RECOVERING", "QUEUED"},
    "RECOVERING": {"QUEUED", "FAILED"},
}
ACTIVE = {"QUEUED", "STARTING", "RUNNING", "PAUSED", "STOPPING"}


def transition(db, experiment, target):
    row = db.execute("SELECT status FROM experiments WHERE id=?", (experiment,)).fetchone()
    if row is None:
        raise KeyError(experiment)
    current = row["status"]
    if target == current:
        return
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid worker transition: {current} -> {target}")
    import time

    from evoforge.storage import Database

    db.execute(
        "UPDATE experiments SET status=?,updated=? WHERE id=?", (target, time.time(), experiment)
    )
    Database.event(db, experiment, "state", {"previous": current, "state": target})


def incarnation(pid):
    try:
        # /proc stat command can include spaces and parentheses: split after last ).
        tail = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        if tail[0] == "Z":
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{tail[19]}"
    except (OSError, ValueError, IndexError, TypeError):
        return None
