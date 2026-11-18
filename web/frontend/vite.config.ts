import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

import { CSP } from "./src/csp";

const csp = (): Plugin => ({
  name: "canada-csp",
  apply: "build",
  transformIndexHtml: {
    order: "pre",
    handler: (html) =>
      html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`),
  },
});

// BASE_PATH: "/" when canada-web serves the build locally; the repo path on GitHub Pages.
export default defineConfig({
  base: process.env.BASE_PATH ?? "/",
  plugins: [csp(), react()],
  build: { sourcemap: false, assetsInlineLimit: 0, modulePreload: { polyfill: false } },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
