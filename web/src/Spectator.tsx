import { useEffect, useState } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Play, Pause, RotateCcw, Focus } from "lucide-react";
import { api } from "./api";
import { SceneView } from "./SceneView";
import { useSpectator } from "./stream";
import type { Experiment, Frame, Recording } from "./types";
function ReplayCard({
  record,
  game,
  focus,
  onFocus,
}: {
  record: Recording & { frames: Frame[] };
  game: string;
  focus: boolean;
  onFocus: () => void;
}) {
  const [index, setIndex] = useState(0),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(1);
  useEffect(() => {
    if (!playing) return;
    const current = record.frames[index],
      next = record.frames[index + 1];
    if (!next) {
      setPlaying(false);
      return;
    }
    const timeout = setTimeout(
      () => setIndex((i) => i + 1),
      Math.max(
        16,
        Math.min(2000, (next.timestamp - current.timestamp) * 1000),
      ) / speed,
    );
    return () => clearTimeout(timeout);
  }, [playing, index, record, speed]);
  const f = record.frames[index];
  return (
    <article className={`panel agent-card ${focus ? "focused" : ""}`}>
      <div className="section-title">
        <h3>
          Agent {record.agent}{" "}
          <span className="muted">· seed {record.seed ?? "unavailable"}</span>
        </h3>
        <button onClick={onFocus} aria-label={`Focus agent ${record.agent}`}>
          <Focus size={16} />
        </button>
      </div>
      <SceneView scene={f?.scene} game={game} text={f?.text} />
      <div className="agent-stats">
        <span>
          Score <b>{f?.score ?? "—"}</b>
        </span>
        <span>
          Reward <b>{f?.reward?.toFixed(3) ?? "—"}</b>
        </span>
        <span>
          Step <b>{f?.step ?? "—"}</b>
        </span>
      </div>
      <div className="toolbar">
        <button onClick={() => setPlaying(!playing)}>
          {playing ? <Pause size={14} /> : <Play size={14} />}{" "}
          {playing ? "Pause replay" : "Play replay"}
        </button>
        <button
          aria-label="Restart replay"
          onClick={() => {
            setIndex(0);
            setPlaying(false);
          }}
        >
          <RotateCcw size={14} />
        </button>
        <label>
          Speed
          <select
            aria-label="Speed"
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          >
            {[0.25, 0.5, 1, 2, 4].map((x) => (
              <option key={x} value={x}>
                {x}×
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Replay frame
        <input
          aria-label={`Replay frame agent ${record.agent}`}
          type="range"
          min={0}
          max={record.frames.length - 1}
          value={index}
          onChange={(e) => {
            setIndex(Number(e.target.value));
            setPlaying(false);
          }}
        />
      </label>
      <p className="muted">
        {index + 1} / {record.frame_count} frames ·{" "}
        {record.sampled ? "Sampled gameplay" : "Generated episode"} ·{" "}
        {record.complete ? "Episode ended" : "Partial recording"}
        {record.dropped ? ` · ${record.dropped} dropped` : ""}
      </p>
    </article>
  );
}
export function Spectator({ run }: { run?: Experiment }) {
  const [mode, setMode] = useState("live"),
    [seed, setSeed] = useState(900),
    [count, setCount] = useState(4),
    [zoom, setZoom] = useState(1),
    [fps, setFps] = useState(30),
    [agent, setAgent] = useState("all"),
    [focused, setFocused] = useState(""),
    [keys, setKeys] = useState<string[]>([]);
  const client = useQueryClient();
  const id = run?.id || "";
  const live = useSpectator(id, mode === "live");
  const list = useQuery({
    queryKey: ["replays", id],
    queryFn: () => api.replays(id),
    enabled: !!id,
    refetchInterval: 5000,
  });
  const records = useQueries({
    queries: keys.map((key) => ({
      queryKey: ["replay", id, key],
      queryFn: () => api.recording(id, key),
      enabled: !!id,
    })),
  });
  const generation = useMutation({
    mutationFn: () =>
      api.generate(id, mode, seed, mode === "population" ? count : 1),
    onSuccess: (data) => {
      setKeys(data.map((x) => x.id));
      void client.invalidateQueries({ queryKey: ["replays", id] });
    },
  });
  if (!run)
    return (
      <div className="empty panel">
        Create or open an experiment to watch gameplay.
      </div>
    );
  const frames = live.frames
    .filter(
      (f) =>
        (agent === "all" || f.agent === agent) &&
        (!focused || focused === f.agent),
    )
    .slice(0, count);
  return (
    <>
      <section className="panel">
        <div className="section-title">
          <div>
            <span className="eyebrow">SPECTATOR</span>
            <h2>A window into the learning process.</h2>
          </div>
          <span className="badge">
            {mode === "live" ? live.status : "Replay"}
          </span>
        </div>
        <div className="toolbar">
          <label>
            Mode
            <select
              aria-label="Mode"
              value={mode}
              onChange={(e) => {
                setMode(e.target.value);
                setKeys([]);
                setFocused("");
              }}
            >
              <option value="live">Live Training</option>
              <option value="champion">Champion Replay</option>
              <option value="population">Population Replay</option>
              <option value="recorded">Recorded Episodes</option>
            </select>
          </label>
          <label>
            Visible agents
            <select
              aria-label="Visible agents"
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              {[1, 2, 4, 6, 9].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          {mode === "live" ? (
            <>
              <label>
                Agent
                <select
                  aria-label="Agent"
                  value={agent}
                  onChange={(e) => setAgent(e.target.value)}
                >
                  <option value="all">All agents</option>
                  {live.frames.map((f) => (
                    <option key={f.agent} value={f.agent}>
                      {f.agent}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Zoom
                <select
                  aria-label="Zoom"
                  value={zoom}
                  onChange={(e) => setZoom(Number(e.target.value))}
                >
                  {[0.75, 1, 1.5, 2].map((n) => (
                    <option key={n} value={n}>
                      {n}×
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Frame rate
                <select
                  aria-label="Frame rate"
                  value={fps}
                  onChange={(e) => setFps(Number(e.target.value))}
                >
                  {[15, 30, 60].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            mode !== "recorded" && (
              <>
                <label>
                  Replay seed
                  <input
                    type="number"
                    min={0}
                    max={2147483647}
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                  />
                </label>
                <button
                  className="primary"
                  disabled={generation.isPending}
                  onClick={() => generation.mutate()}
                >
                  {generation.isPending ? "Generating episode…" : "Load replay"}
                </button>
              </>
            )
          )}
        </div>
        {generation.error && (
          <p role="alert" className="error">
            {generation.error.message}
          </p>
        )}
        {live.gap && mode === "live" && (
          <p className="muted">
            Some frames expired from the telemetry buffer. Showing available
            sampled frames.
          </p>
        )}
        <p className="muted">
          {run.id} · {run.config.game} · worker {run.status.toLowerCase()}.
          Simulation runs independently of playback speed.
        </p>
      </section>
      {mode === "live" ? (
        <div className={`agent-grid ${focused ? "focus-grid" : ""}`}>
          {frames.length ? (
            frames.map((f) => (
              <article key={f.agent} className="panel agent-card">
                <div className="section-title">
                  <h3>Agent {f.agent}</h3>
                  <button
                    aria-label={`Focus agent ${f.agent}`}
                    onClick={() => setFocused(focused ? "" : f.agent)}
                  >
                    <Focus size={16} />
                  </button>
                </div>
                <SceneView
                  scene={f.data.scene}
                  game={run.config.game}
                  text={f.data.text}
                  zoom={zoom}
                  fps={fps}
                />
                <div className="agent-stats">
                  <span>
                    Generation <b>{f.generation}</b>
                  </span>
                  <span>
                    Episode <b>{f.episode_index + 1}</b>
                  </span>
                  <span>
                    Score <b>{f.score}</b>
                  </span>
                  <span>
                    Reward <b>{f.reward.toFixed(3)}</b>
                  </span>
                </div>
                <p className="muted">
                  {new Date(f.timestamp * 1000).toLocaleTimeString()} · step{" "}
                  {f.step} · {run.status === "RUNNING" ? "sampled" : "saved"}{" "}
                  frame #{f.seq}
                </p>
                {f.data.render_error && (
                  <p role="alert">{f.data.render_error}</p>
                )}
              </article>
            ))
          ) : (
            <div className="empty panel">
              Waiting for sampled gameplay. Start a worker to receive actual
              frames.
            </div>
          )}
        </div>
      ) : (
        <>
          <section className="panel">
            <label>
              Saved episode
              <select
                aria-label="Saved episode"
                value={keys.length === 1 ? keys[0] : ""}
                onChange={(e) =>
                  setKeys(e.target.value ? [e.target.value] : [])
                }
              >
                <option value="">Select a recording</option>
                {list.data?.map((r) => (
                  <option value={r.id} key={r.id}>
                    {r.source} · agent {r.agent} · score {r.score} ·{" "}
                    {new Date(r.created * 1000).toLocaleTimeString()}
                  </option>
                ))}
              </select>
            </label>
            {!list.data?.length && (
              <p className="empty">
                No recordings yet. Training records sampled episodes
                automatically.
              </p>
            )}
            {list.error && <p role="alert">{list.error.message}</p>}
          </section>
          <div className="agent-grid">
            {records.map((q, i) =>
              q.data ? (
                (!focused || focused === q.data.agent) && (
                  <ReplayCard
                    key={keys[i]}
                    record={q.data}
                    game={run.config.game}
                    focus={focused === q.data.agent}
                    onFocus={() => setFocused(focused ? "" : q.data!.agent)}
                  />
                )
              ) : (
                <p key={keys[i]} role={q.isError ? "alert" : undefined}>
                  {q.error?.message || "Loading frames…"}
                </p>
              ),
            )}
          </div>
        </>
      )}
    </>
  );
}
