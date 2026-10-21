// Backtest page: per-Watch outcomes, Alert rate and feedback, via the API.
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repo = path.resolve(__dirname, "..", "..");
const python = process.env.FS_PYTHON ?? path.join(repo, ".venv", "bin", "python");

function runPipeline(at: string, payloadDir: string) {
  execFileSync(
    python,
    [
      "-m", "flight_scanner.testing.e2e_stack", "scan",
      "--state-dir", process.env.FS_E2E_STATE_DIR!,
      "--payload-dir", payloadDir,
      "--at", at,
    ],
    { cwd: repo, stdio: "pipe", timeout: 120_000 },
  );
}

test("the backtest page shows a Watch's Deals, Alert rate and feedback", async ({ page, request }) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fs-e2e-backtest-"));
  fs.writeFileSync(
    path.join(dir, "hel-lis-2026-12.json"),
    JSON.stringify({
      currency: "EUR",
      prices: [{ origin: "HEL", destination: "LIS", depart_date: "2026-12-03", price: 70, airline: "TP" }],
    }),
  );
  const watch = await request.post("/api/watches", {
    data: {
      name: "Lisbon backtest",
      origins: { include: [{ kind: "airport", code: "HEL" }] },
      destinations: { include: [{ kind: "airport", code: "LIS" }] },
      trip_pattern: { preset: "one_way_fixed", departure: "2026-12-03" },
      adults: 1,
      price_threshold: { amount_eur: 100, basis: "total" },
    },
  });
  expect(watch.ok()).toBeTruthy();
  const watchId = (await watch.json()).id;
  runPipeline("2026-10-20T08:00:00+00:00", dir); // a threshold-only Deal, alerted
  const [deal] = await (await request.get(`/api/deals?watch_id=${watchId}`)).json();
  expect((await request.post(`/api/deals/${deal.id}/feedback`, { data: { rating: "up" } })).ok()).toBeTruthy();
  runPipeline("2026-10-20T08:30:00+00:00", dir); // builds the backtest of that Deal

  await page.goto("/backtest");
  const row = page.getByRole("table", { name: "Backtest per Watch" }).getByRole("row", { name: /Lisbon backtest/ });
  await expect(row).toContainText("1 / 0"); // rated good / bad
  await row.getByRole("button", { name: "Lisbon backtest" }).click();

  const past = page.getByRole("table", { name: "Past Deals" });
  await expect(past).toContainText("HEL → LIS");
  await expect(past).toContainText("€70");
  await expect(past).toContainText("No Baseline");
  await expect(past).toContainText("Good");
  await expect(page.getByRole("complementary", { name: "Inspector" })).toContainText("Alert rate");
  await page.screenshot({ path: "test-results/backtest.png", fullPage: true });
});
