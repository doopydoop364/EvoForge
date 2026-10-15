import type { Node, Scene } from "./types";

// Older telemetry contains only terminal boards. Present the captured cells;
// never advance a simulation or invent positions missing from that recording.
export function capturedScene(game: string, text: string): Scene | undefined {
  if (game !== "snake" && game !== "flappy") return;
  const rows = text.split("\n");
  const size = rows.length;
  const allowed = game === "snake" ? /^[.Ho*]+$/ : /^[.H# ]+$/;
  if (
    size < 2 ||
    size > 64 ||
    rows.some((row) => row.length !== size || !allowed.test(row))
  )
    return;
  function node(
    id: string,
    asset: string,
    x: number,
    y: number,
    width = 32,
    height = 32,
  ): Node {
    return {
      id,
      kind: "sprite",
      asset,
      x,
      y,
      width,
      height,
      rotation: 0,
      scale_x: 1,
      scale_y: 1,
      layer: 0,
      visible: true,
      opacity: 1,
      animation: null,
      text: "",
      color: "#ffffff",
      font_size: 20,
      hud: false,
      columns: 1,
      tiles: [],
      palette: [],
    };
  }
  const background = node(
    "captured-background",
    game === "snake" ? "board" : "sky",
    0,
    0,
    size * 32,
    size * 32,
  );
  background.layer = -2;
  const nodes = [background];
  if (game === "snake")
    nodes.push({
      ...node("captured-grid", "tile", 0, 0),
      kind: "tilemap",
      layer: -1,
      columns: size,
      tiles: Array(size * size).fill(0),
      palette: ["tile"],
    });
  const symbols: Record<string, string> =
    game === "snake"
      ? { H: "head", o: "body", "*": "food" }
      : { H: "bird", "#": "pipe" };
  rows.forEach((row, y) =>
    [...row].forEach((cell, x) => {
      if (symbols[cell])
        nodes.push(node(`captured-${x}-${y}`, symbols[cell], x * 32, y * 32));
    }),
  );
  return {
    protocol: 1,
    width: size * 32,
    height: size * 32,
    coordinates: "y-down",
    background: "#112622",
    timestamp: 0,
    camera: null,
    animations: {},
    nodes,
  };
}
