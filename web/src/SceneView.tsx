import { useEffect, useMemo, useRef, useState } from "react";
import {
  Application,
  Assets,
  Container,
  Graphics,
  Sprite,
  Text,
  Texture,
} from "pixi.js";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Scene, Node } from "./types";
import { capturedScene } from "./capturedScene";

export function SceneView({
  scene,
  game,
  text = "",
  zoom = 1,
  fps = 30,
}: {
  scene?: Scene | null;
  game: string;
  text?: string;
  zoom?: number;
  fps?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const presentation = useMemo(
    () => scene ?? capturedScene(game, text),
    [scene, game, text],
  );
  const [error, setError] = useState("");
  const [assetError, setAssetError] = useState("");
  const latest = useRef({ scene: presentation, zoom, fps });
  latest.current = { scene: presentation, zoom, fps };
  const manifest = useQuery({
    queryKey: ["manifest", game],
    queryFn: () => api.manifest(game),
    staleTime: Infinity,
    enabled: !!game,
  });
  useEffect(() => {
    if (!host.current || !manifest.data) return;
    const element = host.current;
    const app = new Application();
    let stopped = false;
    let ready = false;
    let previous: Scene | null | undefined;
    let elapsed = 0;
    const sprites = new Map<string, { display: Container; node: Node }>();
    const textures = new Map<string, Texture>();
    const world = new Container();
    const hud = new Container();
    world.sortableChildren = true;
    hud.sortableChildren = true;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    setError("");
    setAssetError("");
    async function init() {
      try {
        await app.init({
          backgroundAlpha: 0,
          antialias: true,
          resizeTo: element,
          resolution: Math.min(devicePixelRatio || 1, 2),
          autoDensity: true,
          preference: "webgl",
        });
        ready = true;
        if (stopped) {
          app.destroy(true, { children: true });
          return;
        }
        app.canvas.setAttribute("aria-label", `${game} gameplay scene`);
        app.canvas.setAttribute("role", "img");
        element.appendChild(app.canvas);
        app.stage.addChild(world, hud);
        await Promise.all(
          Object.entries(manifest.data!.assets).map(async ([id, asset]) => {
            try {
              const url = new URL(asset.url, location.origin);
              if (
                url.origin !== location.origin ||
                !url.pathname.startsWith("/api/v1/games/")
              )
                throw Error("Asset URL must use the local game API");
              // The content-addressed API URLs have no file extension.
              const parser =
                asset.media_type === "image/svg+xml"
                  ? "svg"
                  : ["image/png", "image/webp"].includes(asset.media_type)
                    ? "texture"
                    : null;
              if (!parser) return;
              const texture = await Assets.load<Texture>({
                src: url.href,
                parser,
                data: { scaleMode: asset.scale_mode || "linear" },
              });
              if (!texture) throw Error("No texture returned");
              textures.set(id, texture);
            } catch {
              if (!stopped)
                setAssetError(
                  "Some game graphics could not be loaded. Showing placeholders and the captured text below.",
                );
            }
          }),
        );
        if (stopped) return;
        app.ticker.add((ticker) => {
          const { scene: current, zoom: zoomNow, fps: fpsNow } = latest.current;
          app.ticker.maxFPS = fpsNow;
          if (!current || current.protocol !== 1) return;
          elapsed += ticker.deltaMS / 1000;
          if (previous !== current) {
            const active = new Set<string>();
            const add = (node: Node) => {
              active.add(node.id);
              let entry = sprites.get(node.id);
              const texture = textures.get(node.asset || "");
              if (
                entry &&
                (entry.node.kind !== node.kind ||
                  entry.node.asset !== node.asset ||
                  entry.node.text !== node.text ||
                  entry.node.width !== node.width ||
                  entry.node.height !== node.height ||
                  entry.node.color !== node.color ||
                  entry.node.font_size !== node.font_size)
              ) {
                entry.display.destroy();
                sprites.delete(node.id);
                entry = undefined;
              }
              if (!entry) {
                let display: Container;
                if (node.kind === "text")
                  display = new Text({
                    text: node.text,
                    style: {
                      fontFamily: "system-ui",
                      fontSize: node.font_size,
                      fill: node.color,
                    },
                  });
                else if (node.kind === "sprite" && texture)
                  display = new Sprite(texture);
                else
                  display = new Graphics()
                    .roundRect(
                      0,
                      0,
                      node.width,
                      node.height,
                      Math.min(6, node.width / 4),
                    )
                    .fill(node.kind === "sprite" ? "#d69269" : node.color);
                display.position.set(node.x, node.y);
                (node.hud ? hud : world).addChild(display);
                entry = { display, node };
                sprites.set(node.id, entry);
              }
              const parent = node.hud ? hud : world;
              if (entry.display.parent !== parent)
                parent.addChild(entry.display);
              entry.node = node;
              entry.display.visible = node.visible;
              entry.display.alpha = node.opacity;
              entry.display.zIndex = node.layer;
              entry.display.rotation = node.rotation;
              if (entry.display instanceof Sprite) {
                entry.display.width = node.width;
                entry.display.height = node.height;
                entry.display.scale.x *= node.scale_x;
                entry.display.scale.y *= node.scale_y;
              } else {
                entry.display.scale.set(node.scale_x, node.scale_y);
              }
            };
            for (const node of current.nodes) {
              if (node.kind === "tilemap") {
                node.tiles.forEach((tile, i) => {
                  if (tile >= 0)
                    add({
                      ...node,
                      id: `${node.id}::${i}`,
                      kind: "sprite",
                      asset: node.palette[tile],
                      x: node.x + (i % node.columns) * node.width,
                      y: node.y + Math.floor(i / node.columns) * node.height,
                    });
                });
              } else add(node);
            }
            for (const [id, entry] of sprites)
              if (!active.has(id)) {
                entry.display.destroy();
                sprites.delete(id);
              }
            previous = current;
          }
          const scale = Math.min(
            app.screen.width / current.width,
            app.screen.height / current.height,
          );
          const camera = current.camera || {
            x: current.width / 2,
            y: current.height / 2,
            zoom: 1,
          };
          const factor = scale * camera.zoom * zoomNow;
          world.scale.set(
            factor,
            current.coordinates === "y-up" ? -factor : factor,
          );
          world.position.set(
            app.screen.width / 2 - camera.x * factor,
            app.screen.height / 2 - camera.y * world.scale.y,
          );
          hud.scale.set(scale);
          hud.position.set(
            (app.screen.width - current.width * scale) / 2,
            (app.screen.height - current.height * scale) / 2,
          );
          app.renderer.background.color = current.background;
          app.renderer.background.alpha = 1;
          for (const { display, node } of sprites.values()) {
            const t = reduced ? 1 : Math.min(1, ticker.deltaMS / 80);
            display.x += (node.x - display.x) * t;
            display.y += (node.y - display.y) * t;
            if (!reduced && node.animation && display instanceof Sprite) {
              const anim = current.animations[node.animation];
              const texture = textures.get(
                anim.frames[
                  Math.floor(elapsed * anim.fps) % anim.frames.length
                ],
              );
              if (texture) display.texture = texture;
            }
          }
        });
      } catch (e) {
        if (!stopped)
          setError(e instanceof Error ? e.message : "Renderer unavailable");
      }
    }
    void init();
    return () => {
      stopped = true;
      if (ready) app.destroy(true, { children: true });
    };
  }, [game, manifest.data]);
  if (scene && scene.protocol !== 1)
    return <p role="alert">Unsupported renderer protocol</p>;
  return (
    <div className="scene-wrap">
      <div ref={host} className="scene-canvas" data-testid="scene-canvas" />
      {assetError && (
        <p role="alert" className="scene-warning">
          {assetError}
        </p>
      )}
      {(!presentation || error || manifest.isError) && (
        <pre className="scene-fallback">
          {error ? "Graphics unavailable. " : ""}
          {manifest.isError ? "Assets unavailable. " : ""}
          {text || "Waiting for gameplay frames…"}
        </pre>
      )}
      {!scene && presentation && (
        <p className="scene-caption">Rendered from captured board text.</p>
      )}
      {assetError && presentation && !error && (
        <pre>{text || "Captured text is unavailable."}</pre>
      )}
    </div>
  );
}
