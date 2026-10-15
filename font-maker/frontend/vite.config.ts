// @ts-ignore -- Node's type definitions are not installed; this file only runs in Node, at build time
import { cpSync, existsSync } from "node:fs";
import { defineConfig, Plugin } from "vitest/config";
import react from "@vitejs/plugin-react";

// The help page lives in font-maker/docs/help/ (readable without the app); the build copies it into the app,
// which serves it at /help/... (font_maker/api.py), as the reading app does with docs/help/.
function copyHelp(): Plugin {
  return {
    name: "copy-help",
    closeBundle() {
      if (existsSync("../docs/help")) cpSync("../docs/help", "../src/font_maker/static/help", { recursive: true });
    },
  };
}

// The built screen goes into the Python package, which serves it at "/" (font_maker/api.py).
// For development, `npm run dev` proxies the API to a running Font Maker on port 8676
// (start one with: PYTHONPATH=src:font-maker/src .venv/bin/python -m font_maker --browser,
//  then open http://localhost:5173/?token=<token printed in the page source>).
// The stylesheet is the reading app's (frontend/src/styles.css), so both apps look the same.
export default defineConfig({
  plugins: [react(), copyHelp()],
  build: {
    outDir: "../src/font_maker/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8676", "/files": "http://127.0.0.1:8676", "/help": "http://127.0.0.1:8676" },
    fs: { allow: ["..", "../../frontend/src"] },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
