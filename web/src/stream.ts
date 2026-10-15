import { useEffect, useState } from "react";
import type { LiveFrame } from "./types";
export class FrameBuffer {
  cursor = 0;
  frames = new Map<string, LiveFrame>();
  accept(batch: LiveFrame[], experiment: string) {
    for (const f of batch) {
      if (
        f.experiment !== experiment ||
        !Number.isSafeInteger(f.seq) ||
        f.seq <= this.cursor
      )
        continue;
      this.cursor = f.seq;
      const previous = this.frames.get(f.agent);
      if (previous && f.timestamp < previous.timestamp) continue;
      this.frames.set(f.agent, f);
      if (this.frames.size > 9)
        this.frames.delete(this.frames.keys().next().value!);
    }
    return [...this.frames.values()];
  }
}
export function useSpectator(experiment: string, enabled: boolean) {
  const [state, setState] = useState<{
    frames: LiveFrame[];
    status: string;
    gap: boolean;
  }>({ frames: [], status: "Disconnected", gap: false });
  useEffect(() => {
    if (!enabled || !experiment) return;
    const buffer = new FrameBuffer();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let socket: WebSocket;
    let attempts = 0;
    setState({ frames: [], status: "Connecting", gap: false });
    const connect = () => {
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/experiments/${encodeURIComponent(experiment)}/spectator?since=${buffer.cursor}`,
      );
      socket.onopen = () => {
        attempts = 0;
        setState((s) => ({ ...s, status: "Connected" }));
      };
      socket.onmessage = (event) => {
        try {
          const batch = JSON.parse(event.data);
          if (!Array.isArray(batch.frames)) return;
          const frames = buffer.accept(batch.frames, experiment);
          setState({ frames, status: "Connected", gap: !!batch.gap });
        } catch {
          setState((s) => ({ ...s, status: "Invalid telemetry" }));
        }
      };
      socket.onclose = (event) => {
        if (stopped) return;
        if (event.code === 4401 || event.code === 4403) {
          setState((s) => ({ ...s, status: "Authentication required" }));
          return;
        }
        setState((s) => ({ ...s, status: "Reconnecting" }));
        timer = setTimeout(connect, Math.min(1000 * 2 ** attempts++, 15000));
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [experiment, enabled]);
  return state;
}
