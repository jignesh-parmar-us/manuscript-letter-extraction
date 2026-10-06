// @ts-ignore -- Node's type definitions are not installed; this file only runs in Node, at build time
import { cpSync, existsSync } from "node:fs";
import { defineConfig, Plugin } from "vitest/config";
import react from "@vitejs/plugin-react";

// The help pages live in docs/help/ (one copy, readable without the app); the build copies them into
// the app, which serves them at /help/... (app/api.py).
function copyHelp(): Plugin {
  return {
    name: "copy-help",
    closeBundle() {
      if (existsSync("../docs/help")) cpSync("../docs/help", "../src/letter_extractor/app/static/help", { recursive: true });
    },
  };
}

// The built screen goes into the Python package, which serves it at "/" (app/api.py).
// For development, `npm run dev` proxies the API to a running backend on port 8765
// (start one with: python -m letter_extractor.app --browser --port 8765, then open
//  http://localhost:5173/?token=<token printed in the page source>).
export default defineConfig({
  plugins: [react(), copyHelp()],
  build: {
    outDir: "../src/letter_extractor/app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/files": "http://127.0.0.1:8765",
      "/help": "http://127.0.0.1:8765",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // screen tests click through real components; on a busy machine (or CI) they need more than 5 s
    testTimeout: 20000,
  },
});
