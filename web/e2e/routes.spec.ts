// Route explorer: price history for a chosen route and departure date, via the API.
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const repo = path.resolve(__dirname, "..", "..");
const python = process.env.FS_PYTHON ?? path.join(repo, ".venv", "bin", "python");

function runPipeline(at: string) {
  execFileSync(
    python,
    [
      "-m", "flight_scanner.testing.e2e_stack", "scan",
      "--state-dir", process.env.FS_E2E_STATE_DIR!,
      "--payload-dir", path.join(repo, "tests", "fixtures", "payloads", "fake"),
      "--at", at,
    ],
    { cwd: repo, stdio: "pipe", timeout: 120_000 },
  );
}

test("the route explorer charts a route's price history for a departure date", async ({ page, request }) => {
  const watch = await request.post("/api/watches", {
    data: {
      name: "Barcelona history",
      origins: { include: [{ kind: "airport", code: "HEL" }] },
      destinations: { include: [{ kind: "airport", code: "BCN" }] },
      trip_pattern: { preset: "one_way_fixed", departure: "2026-11-14" },
      adults: 1,
      price_threshold: null,
    },
  });
  expect(watch.ok()).toBeTruthy();
  runPipeline("2026-10-20T06:00:00+00:00");
  runPipeline("2026-10-20T06:30:00+00:00"); // same fare again: still one price level

  await page.goto("/routes");
  await page.getByLabel("Route").selectOption("HEL-BCN");
  await page.getByLabel("Departs").selectOption("2026-11-14");

  await expect(page.getByRole("img", { name: /HEL to BCN.*1 price level/ })).toBeVisible();
  const changes = page.getByRole("table", { name: "Price changes" }).getByRole("row");
  await expect(changes).toHaveCount(2); // header + one change-only row
  await expect(changes.nth(1)).toContainText("€89");
  await expect(changes.nth(1)).toContainText("2×");
  await page.screenshot({ path: "test-results/route-explorer.png", fullPage: true });
});
