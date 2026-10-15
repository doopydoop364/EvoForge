import type { Node, Scene } from "./types";

// Legacy boards provide cells and symbols only. Do not reconstruct unrecorded
// physics, level data, portal types, or player modifiers from those symbols.
export function capturedGeometryScene(text: string): Scene | undefined {
  // The only accepted control sequences are the simulator's ANSI SGR colors.
  // eslint-disable-next-line no-control-regex
  const rows = text.replace(/\x1b\[[0-9;]*m/g, "").split("\n");
  const size = rows.length;
  if (
    size < 7 ||
    size > 64 ||
    rows.some(
      (row) => row.length !== size || !/^[- C>OUWRSGX^v_.#o=|!]+$/.test(row),
    )
  )
    return;
  const modes: Record<string, string> = {
    C: "cube",
    ">": "ship",
    O: "ball",
    U: "ufo",
    W: "wave",
    R: "robot",
    S: "spider",
    G: "swing",
  };
  const nodes: Node[] = [];
  rows.forEach((row, y) =>
    [...row].forEach((cell, x) => {
      if (cell === " " || cell === "_") return;
      const asset =
        modes[cell] ||
        (
          {
            "^": "spike",
            v: "spike",
            ".": "ground",
            "#": "ground",
            "-": "ground",
            o: "orb",
            "=": "pad",
          } as Record<string, string>
        )[cell];
      const color = modes[cell]
        ? "#50dcff"
        : "^vX".includes(cell)
          ? "#ff5c5c"
          : cell === "o"
            ? "#ffda5b"
            : cell === "="
              ? "#68f098"
              : cell === "|"
                ? "#ac80ff"
                : cell === "!"
                  ? "#ffa65c"
                  : "#949eaf";
      nodes.push({
        id: `captured-${x}-${y}`,
        kind: asset ? "sprite" : "text",
        asset: asset || null,
        x: x * 32,
        y: y * 32 + (cell === "v" ? 32 : 0),
        width: 32,
        height: 32,
        scale_x: 1,
        scale_y: cell === "v" ? -1 : 1,
        rotation: 0,
        layer: modes[cell] ? 8 : 0,
        visible: true,
        opacity: 1,
        animation: null,
        text: asset ? "" : cell,
        color,
        font_size: 24,
        hud: false,
        columns: 1,
        tiles: [],
        palette: [],
      });
    }),
  );
  return {
    protocol: 1,
    width: size * 32,
    height: size * 32,
    coordinates: "y-down",
    background: "#102552",
    timestamp: 0,
    camera: null,
    animations: {},
    nodes,
  };
}
