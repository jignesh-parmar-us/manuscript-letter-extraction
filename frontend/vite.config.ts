import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The built screen goes into the Python package, which serves it at "/" (app/api.py).
// For development, `npm run dev` proxies the API to a running backend on port 8765
// (start one with: python -m letter_extractor.app --browser --port 8765, then open
//  http://localhost:5173/?token=<token printed in the page source>).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/letter_extractor/app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/files": "http://127.0.0.1:8765",
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
