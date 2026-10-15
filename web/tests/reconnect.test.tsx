import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSpectator } from "../src/stream";
class Socket {
  static instances: Socket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
}
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Socket.instances = [];
});
it("reconnects with the accepted cursor and resets on experiment changes", () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  const { result, rerender, unmount } = renderHook(
    ({ id }) => useSpectator(id, true),
    { initialProps: { id: "first" } },
  );
  const first = Socket.instances[0];
  act(() => {
    first.onopen?.();
    first.onmessage?.({
      data: JSON.stringify({
        frames: [{ seq: 5, experiment: "first", agent: "0", timestamp: 10 }],
        gap: true,
      }),
    });
  });
  expect(result.current.frames).toHaveLength(1);
  expect(result.current.gap).toBe(true);
  act(() => first.onclose?.({ code: 1006 }));
  expect(result.current.status).toBe("Reconnecting");
  act(() => vi.advanceTimersByTime(1000));
  expect(Socket.instances[1].url).toContain("since=5");
  rerender({ id: "second" });
  expect(first.close).toHaveBeenCalledTimes(0);
  expect(Socket.instances[1].close).toHaveBeenCalled();
  expect(result.current.frames).toHaveLength(0);
  expect(Socket.instances[2].url).toContain("/second/spectator?since=0");
  unmount();
  expect(Socket.instances[2].close).toHaveBeenCalled();
});
it("does not retry rejected authentication", () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  const { result, unmount } = renderHook(() => useSpectator("private", true));
  act(() => Socket.instances[0].onclose?.({ code: 4401 }));
  expect(result.current.status).toBe("Authentication required");
  act(() => vi.advanceTimersByTime(60000));
  expect(Socket.instances).toHaveLength(1);
  unmount();
});
