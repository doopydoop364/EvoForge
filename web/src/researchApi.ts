import { request } from "./api";
import type { Config, Experiment, Metric } from "./types";
export type Bookmark = {
  id: string;
  title: string;
  view: string;
  generation: number | null;
  agent: string | null;
  right_agent?: string | null;
  notes: string;
  created: number;
};
export type ResearchMeta = {
  notes: string;
  tags: string[];
  weight_bytes: number;
  indexed_generation?: number;
  manifest?: Record<string, unknown>;
  bookmarks: Bookmark[];
  champions?: {
    generation: number;
    validation_fitness: number;
    agent: number;
  }[];
};
export type AgentNode = {
  id: string;
  generation: number;
  slot: number;
  operation: string;
  parents: string[];
  fingerprint: string | null;
  fitness: number | null;
  weights_available: boolean;
};
export type Family = {
  generation: number;
  indexed_generation?: number;
  total: number;
  offset: number;
  limit: number;
  nodes: AgentNode[];
};
export type Genetic = {
  left: string;
  right: string;
  left_fingerprint: string;
  right_fingerprint: string;
  note: string;
  layers: {
    name: string;
    shape: number[];
    count: number;
    changed: number;
    rmse: number;
    max_absolute_difference: number;
    samples: { index: number; left: number; right: number; delta: number }[];
  }[];
};
export type Job = {
  id: string;
  kind: string;
  experiments: string[];
  status: string;
  progress: number;
  created: number;
  finished?: number;
  error?: string;
  result?: Record<string, unknown>;
  request: Record<string, unknown>;
};
export type Backup = {
  id: string;
  experiment: string;
  bytes: number;
  created: number;
  error?: string;
};
export type Storage = {
  runs: {
    id: string;
    status: string;
    archived: boolean;
    bytes: number;
    research_bytes: number;
    replay_bytes: number;
  }[];
  disk_total: number;
  disk_free: number;
  backup_bytes: number;
  research_jobs: number;
};
const path = (id: string) => `/experiments/${encodeURIComponent(id)}/research`;
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});
export const research = {
  catalog: () =>
    request<{ id: string; tags: string[]; notes_preview: string }[]>(
      "/research/catalog",
    ),
  meta: (id: string) => request<ResearchMeta>(path(id)),
  annotate: (id: string, notes: string, tags: string[]) =>
    request(path(id), json("PUT", { notes, tags })),
  index: (id: string) => request(`${path(id)}/index`, json("POST")),
  family: (id: string, generation?: number, offset = 0) =>
    request<Family>(
      `${path(id)}/family?offset=${offset}${generation === undefined ? "" : `&generation=${generation}`}`,
    ),
  history: (id: string) =>
    request<{
      rows: Metric[];
      total: number;
      sampled: boolean;
      sampling: string;
    }>(`${path(id)}/history`),
  generation: (id: string, generation: number) =>
    request<{ measurement: Metric | null }>(
      `${path(id)}/generations/${generation}`,
    ),
  genetics: (id: string, left: string, right: string) =>
    request<Genetic>(
      `${path(id)}/genetics?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    ),
  bookmark: (id: string, value: Omit<Bookmark, "id" | "created">) =>
    request(`${path(id)}/bookmarks`, json("POST", value)),
  deleteBookmark: (id: string, key: string) =>
    request(`${path(id)}/bookmarks/${key}`, json("DELETE")),
  jobs: () => request<Job[]>("/research/jobs"),
  submit: (
    kind: string,
    experiments: string[],
    seed = 700000,
    episodes = 8,
    agents?: string[],
    protocol = "shared_scenarios",
  ) =>
    request<Job>(
      "/research/jobs",
      json("POST", {
        protocol,
        kind,
        experiments,
        seed,
        episodes,
        ...(agents ? { agents } : {}),
      }),
    ),
  cancel: (key: string) =>
    request(`/research/jobs/${key}/cancel`, json("POST")),
  removeJob: (key: string) => request(`/research/jobs/${key}`, json("DELETE")),
  storage: () => request<Storage>("/research/storage"),
  retain: (id: string, weight_mib: number, remove_replays: boolean) =>
    request(
      `${path(id)}/retention`,
      json("PUT", { weight_mib, remove_replays }),
    ),
  backups: () => request<Backup[]>("/research/backups"),
  verify: (key: string) =>
    request<{ verified: boolean; files: number }>(
      `/research/backups/${key}/verify`,
      json("POST"),
    ),
  restore: (key: string, destination: string) =>
    request<Experiment>(
      `/research/backups/${key}/restore`,
      json("POST", { destination }),
    ),
  removeBackup: (key: string) =>
    request(`/research/backups/${key}`, json("DELETE")),
  batch: (prefix: string, seeds: number[], config: Config) =>
    request<Experiment[]>(
      "/research/batches",
      json("POST", { prefix, seeds, config }),
    ),
  async importBackup(file: File) {
    const response = await fetch("/api/v1/research/backups/import", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/zip" },
      body: file,
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string" ? data.detail : "Backup import failed",
      );
    return data as Backup;
  },
};
