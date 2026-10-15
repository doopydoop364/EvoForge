import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";
import { ExperimentForm } from "../src/ExperimentForm";
import { api } from "../src/api";
import { SceneView } from "../src/SceneView";
import { MetricChart } from "../src/Analytics";
import { WorkerLog } from "../src/WorkerLog";
import { capturedScene } from "../src/capturedScene";
import { Spectator } from "../src/Spectator";
import * as stream from "../src/stream";
import type { Experiment } from "../src/types";
vi.mock("pixi.js", () => ({
  Application: class {
    async init() {
      throw Error("No WebGL");
    }
    destroy() {}
  },
  Assets: { load: vi.fn() },
  Container: class {},
  Graphics: class {},
  Sprite: class {},
  Text: class {},
}));
const game = {
  id: "coin",
  name: "Coin prediction",
  version: "1.0.0",
  observation_size: 4,
  action_size: 2,
  score_name: "correct",
};
const completedRun: Experiment = {
  id: "finished",
  status: "COMPLETED",
  archived: 0,
  created: 1,
  updated: 2,
  game_version: "1.0.0",
  config: {
    game: "coin",
    mode: "evolution",
    generations: 20,
    population: 4,
    elites: 1,
    ppo_candidates: 0,
    ppo_episodes: 1,
    eval_episodes: 1,
    size: 10,
    max_steps: 50,
    seed: 42,
    hidden: [8],
    mutation_probability: 0.1,
    mutation_sigma: 0.1,
    game_config: {},
    environment_step_budget: null,
  },
  worker: {
    generation: 20,
    heartbeat: 1792015612,
    pid: 12,
    identity: "worker",
    error: null,
    request: null,
  },
};
function wrap(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {component}
    </QueryClientProvider>,
  );
}
function mockBackend() {
  vi.spyOn(api, "health").mockResolvedValue({ status: "ok" });
  vi.spyOn(api, "runs").mockResolvedValue([]);
  vi.spyOn(api, "games").mockResolvedValue([game]);
  vi.spyOn(api, "dashboard").mockResolvedValue({
    active_workers: 0,
    experiments: 0,
    latest: {},
    resources: {
      cpu_count: 2,
      load_average: [0.2],
      memory_used_bytes: 100,
      memory_total_bytes: 200,
      gpu: { available: false, note: "CPU execution" },
    },
    activity: [],
    warnings: [],
  });
}
describe("workspace", () => {
  it("selects a run with results by default and explains an explicitly selected empty run", async () => {
    mockBackend();
    const empty = {
      ...completedRun,
      id: "empty",
      status: "CREATED",
      worker: null,
    };
    vi.spyOn(api, "runs").mockResolvedValue([empty, completedRun]);
    const dashboard = await api.dashboard();
    vi.spyOn(api, "dashboard").mockResolvedValue({
      ...dashboard,
      latest: { finished: { generation: 19, hall_of_fame: 1.84 } },
    });
    vi.spyOn(api, "metrics").mockImplementation(async (id) =>
      id === "finished"
        ? [{ generation: 19, hall_of_fame: 1.84, environment_steps: 77505 }]
        : [],
    );
    wrap(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText("Open experiment")).toHaveValue("finished"),
    );
    expect(await screen.findByText("77,505")).toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByLabelText("Open experiment"),
      "empty",
    );
    expect(
      await screen.findByText(/empty has no measured generations yet/),
    ).toBeInTheDocument();
  });
  it("requires a generation extension before continuing a completed run", async () => {
    mockBackend();
    vi.spyOn(api, "runs").mockResolvedValue([completedRun]);
    vi.spyOn(api, "metrics").mockResolvedValue([]);
    vi.spyOn(api, "checkpoints").mockResolvedValue([]);
    wrap(<App />);
    await screen.findByText("Backend connected");
    await userEvent.click(screen.getByRole("button", { name: "Experiments" }));
    expect(
      await screen.findByRole("button", {
        name: "Continue training",
      }),
    ).toBeDisabled();
    expect(screen.getByText(/Generation limit reached/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Extend training" }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "This does not start a worker",
    );
  });
  it("renders an honest empty dashboard", async () => {
    mockBackend();
    wrap(<App />);
    expect(
      await screen.findByText("Your first generation starts here."),
    ).toBeInTheDocument();
    expect(screen.getByText("Backend connected")).toBeInTheDocument();
  });
  it("persists theme without saving credentials", async () => {
    mockBackend();
    localStorage.clear();
    wrap(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(localStorage.getItem("evoforge-theme")).toBe("light");
    expect(localStorage.length).toBe(1);
  });
  it("shows plugin discovery navigation", async () => {
    mockBackend();
    vi.spyOn(api, "scene").mockResolvedValue({ text: "Coin state" });
    vi.spyOn(api, "manifest").mockResolvedValue({
      game: "coin",
      protocol: 1,
      assets: {},
    });
    wrap(<App />);
    await screen.findByText("Backend connected");
    await userEvent.click(
      screen.getByRole("button", { name: "Games & Plugins" }),
    );
    expect(await screen.findByText("Coin prediction")).toBeInTheDocument();
  });
  it("has a mobile navigation control and skip link", () => {
    mockBackend();
    wrap(<App />);
    expect(
      screen.getByRole("button", { name: "Toggle navigation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Skip to content" }),
    ).toHaveAttribute("href", "#main");
  });
});
describe("configuration", () => {
  it("creates with parsed custom settings", async () => {
    const submit = vi.fn();
    wrap(
      <ExperimentForm
        games={[game]}
        onSubmit={submit}
        onCancel={() => {}}
        pending={false}
      />,
    );
    await userEvent.type(screen.getByLabelText("Experiment name"), "coin-run");
    await userEvent.click(
      screen.getByRole("button", { name: "Create experiment" }),
    );
    expect(submit).toHaveBeenCalledWith(
      "coin-run",
      expect.objectContaining({ game: "coin", hidden: [64] }),
    );
  });
  it("explains invalid architecture and JSON", async () => {
    const submit = vi.fn();
    wrap(
      <ExperimentForm
        games={[game]}
        onSubmit={submit}
        onCancel={() => {}}
        pending={false}
      />,
    );
    fireEvent.change(screen.getByLabelText("Experiment name"), {
      target: { value: "coin" },
    });
    fireEvent.change(screen.getByLabelText("Hidden widths"), {
      target: { value: "0" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Create experiment" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Hidden widths");
    expect(submit).not.toHaveBeenCalled();
  });
});
describe("rendering and analytics", () => {
  it("keeps text mode independent of graphical assets, even when a scene is supplied", () => {
    const manifest = vi.spyOn(api, "manifest");
    const scene = capturedScene("snake", "Hoo\n...\n..*");
    wrap(
      <SceneView
        display="text"
        game="snake"
        scene={scene}
        text="Captured text"
      />,
    );
    expect(screen.getByText("Captured text")).toBeInTheDocument();
    expect(manifest).not.toHaveBeenCalled();
    expect(document.querySelector("canvas")).toBeNull();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("treats a text-only game as supported without requesting a manifest", () => {
    const manifest = vi.spyOn(api, "manifest");
    wrap(<SceneView game="geometrydash" text="--X-------" />);
    expect(screen.getByText("--X-------")).toBeInTheDocument();
    expect(
      screen.getByText(/This recording has no graphical scene/),
    ).toBeInTheDocument();
    expect(manifest).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("labels inactive telemetry independently of its connected socket", async () => {
    vi.spyOn(stream, "useSpectator").mockReturnValue({
      frames: [],
      status: "Connected",
      gap: false,
    });
    vi.spyOn(api, "replays").mockResolvedValue([]);
    wrap(<Spectator run={completedRun} />);
    expect(screen.getByLabelText("Display")).toHaveValue("text");
    expect(screen.getByText("Saved frames")).toBeInTheDocument();
    expect(screen.getByLabelText("Mode")).toHaveDisplayValue(
      "Last Training Frames",
    );
    expect(
      screen.getByText(/Telemetry connection: Connected/),
    ).toHaveTextContent("No live training is running");
    await userEvent.click(
      screen.getByRole("button", { name: "Open champion replay" }),
    );
    expect(screen.getByLabelText("Mode")).toHaveValue("champion");
    expect(
      screen.getByRole("button", { name: "Load replay" }),
    ).toBeInTheDocument();
  });
  it("renders legacy cells at their captured positions and rejects unrelated text", () => {
    const scene = capturedScene("snake", "Hoo\n...\n..*");
    expect(scene?.nodes.filter((n) => n.asset === "head")).toEqual([
      expect.objectContaining({ x: 0, y: 0 }),
    ]);
    expect(scene?.nodes.find((n) => n.asset === "food")).toMatchObject({
      x: 64,
      y: 64,
    });
    expect(scene?.nodes.filter((n) => n.asset === "body")).toHaveLength(2);
    const bird = capturedScene("flappy", "H.#\n.. \n..#")?.nodes.find(
      (n) => n.asset === "bird",
    );
    expect(bird?.x).toBe(0);
    expect(bird!.y + bird!.height / 2).toBe(16);
    expect(bird!.width / bird!.height).toBeCloseTo(34 / 24);
    expect(capturedScene("snake", "arbitrary output")).toBeUndefined();
    expect(capturedScene("coin", "H.\n.*")).toBeUndefined();
    expect(capturedScene("snake", "H.\n..*")).toBeUndefined();
  });
  it("renders only recorded Geometry Dash cells, colors, mode symbols and diagnostic portal labels", () => {
    const board =
      "-------\n C>OUWR\n SGXov \n =|!   \n       \n.^.....\n### ###";
    const scene = capturedScene("geometrydash", board)!;
    expect(scene.nodes.find((n) => n.asset === "cube")).toMatchObject({
      x: 32,
      y: 32,
      color: "#50dcff",
    });
    expect(scene.nodes.find((n) => n.asset === "ship")).toMatchObject({
      x: 64,
      y: 32,
    });
    expect(scene.nodes.find((n) => n.text === "X")?.color).toBe("#ff5c5c");
    expect(scene.nodes.find((n) => n.text === "|")?.asset).toBeNull();
    expect(scene.camera).toBeNull();
    expect(
      capturedScene(
        "geometrydash",
        board.replace("C", "\u001b[38;2;80;220;255mC\u001b[0m"),
      ),
    ).toEqual(scene);
    expect(capturedScene("geometrydash", "not a board")).toBeUndefined();
  });
  it("keeps original Geometry Dash artwork optional without drawing substitute sprites", async () => {
    vi.spyOn(api, "manifest").mockResolvedValue({
      game: "geometrydash",
      protocol: 1,
      assets: {},
    });
    const text =
      "-------\n C     \n       \n       \n       \n.......\n#######";
    wrap(<SceneView game="geometrydash" text={text} />);
    expect(
      await screen.findByText(/Original Geometry Dash artwork is unavailable/),
    ).toBeInTheDocument();
    expect(document.querySelector("pre")?.textContent).toBe(text);
    expect(document.querySelector("canvas")).toBeNull();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("makes structured logs readable while preserving plain output and raw JSON", async () => {
    wrap(
      <WorkerLog
        text={
          'Starting worker\n{"generation":19,"best_score":3.66,"environment_steps":77505}\npartial {line'
        }
      />,
    );
    expect(screen.getByText("Generation 19")).toBeInTheDocument();
    expect(screen.getByText("Steps 77,505")).toBeInTheDocument();
    expect(screen.getByText("partial {line")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Raw worker output"));
    expect(screen.getByText(/"generation":19/)).toBeVisible();
  });
  it("shows text fallback when assets or WebGL are missing", async () => {
    vi.spyOn(api, "manifest").mockResolvedValue({
      game: "coin",
      protocol: 1,
      assets: {},
    });
    wrap(<SceneView game="coin" text="Measured coin state" />);
    await waitFor(() =>
      expect(screen.getByText(/Measured coin state/)).toBeInTheDocument(),
    );
  });
  it("shows missing metrics explicitly", () => {
    wrap(<MetricChart rows={[]} keys={["mean_train"]} title="Fitness" />);
    expect(
      screen.getByText("No measured data available yet."),
    ).toBeInTheDocument();
  });
});
