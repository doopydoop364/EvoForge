import type { Node, Scene } from "./types";
import { capturedGeometryScene } from "./geometryScene";

// Older telemetry contains only terminal boards. Present the captured cells;
// never advance a simulation or invent positions missing from that recording.
export function capturedScene(game: string, text: string): Scene | undefined {
  if (game === "geometrydash") return capturedGeometryScene(text);
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
    game === "flappy" ? size * 32 - (size * 32 * 512) / 288 : 0,
    size * 32,
    game === "flappy" ? (size * 32 * 512) / 288 : size * 32,
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
      if (game === "flappy" && cell === "#") return;
      if (symbols[cell])
        nodes.push(
          node(
            `captured-${x}-${y}`,
            symbols[cell],
            x * 32,
            y * 32 + (game === "flappy" ? (32 - (32 * 24) / 34) / 2 : 0),
            32,
            game === "flappy" ? (32 * 24) / 34 : 32,
          ),
        );
    }),
  );
  const groundHeight =
    game === "flappy" ? Math.round((size * 32 * 112) / 336) : 0;
  if (game === "flappy") {
    for (let x = 0; x < size; x++) {
      for (let y = 0; y < size; y++) {
        if (rows[y][x] !== "#") continue;
        const start = y;
        while (y + 1 < size && rows[y + 1][x] === "#") y++;
        const pipe = node(
          `captured-pipe-${x}-${start}`,
          "pipe",
          x * 32,
          start === 0 ? (y + 1) * 32 : start * 32,
          32,
          (y - start + 1) * 32,
        );
        if (start === 0) pipe.scale_y = -1;
        nodes.push(pipe);
      }
    }
    nodes.push({
      ...node(
        "captured-ground",
        "ground",
        0,
        size * 32,
        size * 32,
        groundHeight,
      ),
      layer: 2,
    });
  }
  return {
    protocol: 1,
    width: size * 32,
    height: size * 32 + groundHeight,
    coordinates: "y-down",
    background: game === "snake" ? "#b2bd08" : "#4ec0ca",
    timestamp: 0,
    camera: null,
    animations: {},
    nodes,
  };
}
