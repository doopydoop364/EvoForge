import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: process.env.EVOFORGE_BACKEND || "http://127.0.0.1:8765",
        ws: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { charts: ["recharts"], renderer: ["pixi.js"] } },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
