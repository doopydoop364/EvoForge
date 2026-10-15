import type {
  Config,
  Experiment,
  Game,
  Metric,
  DashboardData,
  Manifest,
  Recording,
  Frame,
  Scene,
} from "./types";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail
                .map(
                  (d: { loc: string[]; msg: string }) =>
                    `${d.loc.slice(1).join(".")}: ${d.msg}`,
                )
                .join("; ")
            : message;
    } catch {
      /* Keep useful HTTP status for non-JSON responses. */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
const runPath = (id: string) => `/experiments/${encodeURIComponent(id)}`;
export const api = {
  health: () => request<{ status: string }>("/health"),
  games: () => request<Game[]>("/games"),
  runs: () => request<Experiment[]>("/experiments"),
  workers: () => request<Experiment[]>("/workers"),
  dashboard: () => request<DashboardData>("/dashboard"),
  metrics: (id: string) => request<Metric[]>(`${runPath(id)}/metrics`),
  create: (id: string, config: Config) =>
    request<Experiment>("/experiments", {
      method: "POST",
      body: JSON.stringify({ id, config }),
    }),
  update: (id: string, config: Config) =>
    request<Experiment>(runPath(id), {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  action: (id: string, action: string, destination?: string) =>
    request<Experiment>(
      `${runPath(id)}${action === "archive" ? "" : `/${action}`}`,
      {
        method: action === "archive" ? "DELETE" : "POST",
        ...(destination ? { body: JSON.stringify({ destination }) } : {}),
      },
    ),
  login: (token: string) =>
    request("/session", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
  logout: () => request("/session", { method: "DELETE" }),
  manifest: (game: string) =>
    request<Manifest>(`/games/${encodeURIComponent(game)}/manifest`),
  scene: (game: string) =>
    request<{ scene?: Scene; text: string }>(
      `/games/${encodeURIComponent(game)}/scene`,
    ),
  replays: (id: string) => request<Recording[]>(`${runPath(id)}/replays`),
  generate: (id: string, mode: string, seed: number, limit: number) =>
    request<Recording[]>(`${runPath(id)}/replays`, {
      method: "POST",
      body: JSON.stringify({ mode, seed, limit }),
    }),
  async recording(id: string, key: string) {
    let frames: Frame[] = [];
    let item: Recording;
    do {
      item = await request<Recording & { frames: Frame[] }>(
        `${runPath(id)}/replays/${key}?offset=${frames.length}&limit=256`,
      );
      frames = frames.concat(item.frames || []);
    } while (frames.length < item.frame_count);
    return { ...item, frames };
  },
  logs: (id: string) =>
    request<{ text: string; truncated: boolean }>(`${runPath(id)}/logs`),
  checkpoints: (id: string) =>
    request<{ name: string; bytes: number; updated: number }[]>(
      `${runPath(id)}/checkpoints`,
    ),
  compare: (ids: string[], budget?: number) =>
    request<{
      environment_step_budget: number;
      note: string;
      results: Record<string, number | string>[];
    }>(
      `/compare?experiments=${ids.map(encodeURIComponent).join(",")}${budget ? `&budget=${budget}` : ""}`,
    ),
  async export(id: string, format: "csv" | "json") {
    const response = await fetch(
      `/api/v1${runPath(id)}/export?format=${format}`,
      { credentials: "same-origin" },
    );
    if (!response.ok) throw new ApiError(response.status, "Export failed");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${id}-metrics.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  },
};
