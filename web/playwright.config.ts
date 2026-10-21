import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// Random high ports, chosen once in the main process; workers inherit them through the env.
const pick = () => String(20000 + Math.floor(Math.random() * 20000));
process.env.FS_E2E_API_PORT ??= pick();
process.env.FS_E2E_WEB_PORT ??= pick();
const apiPort = process.env.FS_E2E_API_PORT;
const webPort = process.env.FS_E2E_WEB_PORT;

const repo = path.resolve(__dirname, "..");
const python = process.env.FS_PYTHON ?? path.join(repo, ".venv", "bin", "python");
process.env.FS_E2E_STATE_DIR ??= path.join(repo, ".e2e", `run-${apiPort}`);

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${webPort}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m flight_scanner.testing.e2e_stack serve --state-dir ${process.env.FS_E2E_STATE_DIR} --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/health`,
      cwd: repo,
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      // `npm run build` first; the smoke test runs the production server.
      command: `npx next start --hostname 127.0.0.1 -p ${webPort}`,
      url: `http://127.0.0.1:${webPort}/deals`,
      env: { API_URL: `http://127.0.0.1:${apiPort}`, NEXT_TELEMETRY_DISABLED: "1" },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
