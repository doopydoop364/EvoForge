import sqlite3

from evoforge.telemetry import FrameChannel, Replay, TrainingPublisher
from evoforge.trainer import Config, Trainer


def test_bounded_channel_multiple_readers_and_backpressure(tmp_path):
    channel = FrameChannel(tmp_path)
    for i in range(300):
        assert channel.publish({"index": i})
    first = channel.read()
    assert len(first) == 256 and first[0]["index"] == 44
    assert channel.read() == first
    assert channel.read(first[-1]["seq"]) == []
    db = sqlite3.connect(channel.path)
    try:
        db.execute("BEGIN IMMEDIATE")
        assert not channel.publish({"dropped": True})
    finally:
        db.rollback()
        db.close()
    assert not channel.publish({"large": "x" * 70000})


def test_actual_game_frames_and_independent_replay(tmp_path):
    cfg = Config(
        game="coin",
        mode="evolution",
        population=2,
        elites=1,
        ppo_candidates=0,
        generations=1,
        eval_episodes=1,
        hidden=8,
    )
    publisher = TrainingPublisher(tmp_path, "coin", sample_interval=0)
    trainer = Trainer(cfg, tmp_path, telemetry=publisher)
    trainer.run()
    frames = publisher.channel.read()
    assert frames and all("Coin:" in f["data"]["text"] for f in frames)
    assert frames[-1]["truncated"]
    assert all(
        {"experiment", "agent", "generation", "episode", "seq", "timestamp", "score", "reward"}
        <= f.keys()
        for f in frames
    )
    for mode in ["champion", "population"]:
        replay = Replay(tmp_path, mode)
        try:
            result = replay.tick()
            assert result[0]["mode"] == mode and "Coin:" in result[0]["data"]["text"]
        finally:
            replay.close()
