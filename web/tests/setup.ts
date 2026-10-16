import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
// Node 25+ exposes a host localStorage getter without a backing file. Keep unit
// tests on isolated browser-like storage; Playwright tests the real browser store.
const values = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => {
    values.set(key, String(value));
  },
  removeItem: (key: string) => {
    values.delete(key);
  },
  clear: () => values.clear(),
  key: (index: number) => [...values.keys()][index] ?? null,
  get length() {
    return values.size;
  },
});
afterEach(() => {
  cleanup();
  values.clear();
});
window.scrollTo = vi.fn();
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }),
});
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
