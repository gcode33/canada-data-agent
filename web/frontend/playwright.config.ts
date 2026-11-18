import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against the production build (A8 §13): the CSP <meta> exists only there.
// BASE_PATH lets the same suite run against the GitHub Pages build (served under the repo path).
const BASE = process.env.BASE_PATH ?? "/";
const URL = `http://127.0.0.1:4173${BASE}`;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: URL, ...devices["Desktop Chrome"] },
  webServer: {
    command: "npm run preview",
    url: URL,
    reuseExistingServer: !process.env.CI,
  },
});
