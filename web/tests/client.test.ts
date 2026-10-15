import { describe, it, expect, vi, afterEach } from "vitest";
import { api, request, ApiError } from "../src/api";
import { FrameBuffer } from "../src/stream";
import type { LiveFrame } from "../src/types";
afterEach(() => vi.unstubAllGlobals());
describe("central API client", () => {
  it("sends same-origin credentials and useful validation errors", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [{ loc: ["body", "population"], msg: "Too small" }],
        }),
      });
    vi.stubGlobal("fetch", fetch);
    await expect(request("/experiments")).rejects.toThrow(
      "population: Too small",
    );
    expect(fetch.mock.calls[0][1].credentials).toBe("same-origin");
  });
  it("preserves authentication status", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Token required" }),
        }),
    );
    await expect(api.health()).rejects.toEqual(
      new ApiError(401, "Token required"),
    );
  });
  it("handles non-JSON failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw Error();
        },
      }),
    );
    await expect(api.games()).rejects.toThrow("502");
  });
  it.each([
    "duplicate",
    "rename",
    "archive",
    "unarchive",
    "start",
    "pause",
    "resume",
    "stop",
  ])("routes %s through the backend", async (action) => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ id: "run" }) });
    vi.stubGlobal("fetch", fetch);
    await api.action("run", action, "copy");
    expect(fetch.mock.calls[0][0]).toBe(
      `/api/v1/experiments/run${action === "archive" ? "" : `/${action}`}`,
    );
    expect(fetch.mock.calls[0][1].method).toBe(
      action === "archive" ? "DELETE" : "POST",
    );
  });
  it("loads every recorded page without inventing frames", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ frame_count: 2, frames: [{ step: 4 }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ frame_count: 2, frames: [{ step: 9 }] }),
      });
    vi.stubGlobal("fetch", fetch);
    expect(
      (await api.recording("run", "key")).frames.map((f) => f.step),
    ).toEqual([4, 9]);
  });
});
const frame = (seq: number, agent = "0", timestamp = seq) =>
  ({ seq, agent, timestamp, experiment: "run" }) as LiveFrame;
describe("bounded telemetry", () => {
  it("rejects duplicates, old sequences and unrelated experiments", () => {
    const b = new FrameBuffer();
    b.accept([frame(3)], "run");
    b.accept([frame(3), frame(2), { ...frame(4), experiment: "other" }], "run");
    expect(b.cursor).toBe(3);
    expect([...b.frames.values()]).toEqual([frame(3)]);
  });
  it("does not regress timestamps and keeps its reconnect cursor", () => {
    const b = new FrameBuffer();
    b.accept([frame(3), frame(4, "0", 1)], "run");
    expect(b.cursor).toBe(4);
    expect(b.frames.get("0")?.timestamp).toBe(3);
  });
  it("bounds visible agent buffers", () => {
    const b = new FrameBuffer();
    b.accept(
      Array.from({ length: 100 }, (_, i) => frame(i + 1, String(i))),
      "run",
    );
    expect(b.frames.size).toBe(9);
  });
});
