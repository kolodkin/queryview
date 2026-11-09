import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

// The Claude Code web container ships a Chromium at a fixed path and can't
// download the pinned revision; PLAYWRIGHT_CHROMIUM_EXECUTABLE overrides.
const webChromium = "/opt/pw-browsers/chromium";
const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  (process.env.CLAUDE_CODE_REMOTE === "true" && existsSync(webChromium) ? webChromium : undefined);

export default defineConfig({
  testDir: "e2e",
  // Balance individual tests across workers, not whole files.
  fullyParallel: true,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: process.env.E2E_WORKERS ? Number(process.env.E2E_WORKERS) : "100%",
  reporter: [["list"], ["html", { outputFolder: "report", open: "never" }]],
  // A failing test reruns once in CI, recording a trace: recording every
  // run costs about a third of the suite's time.
  retries: process.env.CI ? 1 : 0,
  use: {
    viewport: { width: 1280, height: 900 },
    trace: "on-first-retry",
    launchOptions: { args: ["--no-sandbox"], executablePath },
  },
});
