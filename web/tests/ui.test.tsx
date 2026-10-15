import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";
import { ExperimentForm } from "../src/ExperimentForm";
import { api } from "../src/api";
import { SceneView } from "../src/SceneView";
import { MetricChart } from "../src/Analytics";
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
