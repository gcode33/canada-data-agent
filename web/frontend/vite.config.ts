import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// The policy from A8 §10/§11. Injected only into the built page: Vite's dev server needs an
// inline script, and every CSP test runs against the build. `frame-ancestors` is left out
// because browsers ignore it in a <meta> tag.
export const CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'self'",
  "require-trusted-types-for 'script'",
  "trusted-types 'none'",
].join("; ");

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
