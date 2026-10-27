// Route explorer: price history for a chosen route and departure date, via the API.
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repo = path.resolve(__dirname, "..", "..");
const python = process.env.FS_PYTHON ?? path.join(repo, ".venv", "bin", "python");

function runPipeline(at: string, payloadDir = path.join(repo, "tests", "fixtures", "payloads", "fake")) {
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
  await page.getByRole("combobox", { name: "Route" }).fill("helsinki barcelona");
  await page.getByRole("option", { name: /Helsinki HEL → Barcelona BCN/ }).click();
  await expect(page.getByText("Showing")).toContainText("Helsinki HEL → Barcelona BCN");
  await page.getByRole("group", { name: "Departs" }).getByRole("button", { name: "Sat 14 Nov" }).click();

  await expect(page.getByRole("img", { name: /HEL to BCN.*1 price level/ })).toBeVisible();
  const changes = page.getByRole("table", { name: "Price changes" }).getByRole("row");
  await expect(changes).toHaveCount(2); // header + one change-only row
  await expect(changes.nth(1)).toContainText("€89");
  await expect(changes.nth(1)).toContainText("2×");
  await page.screenshot({ path: "test-results/route-explorer.png", fullPage: true });
});

test("the route explorer draws the Baseline band behind the price history", async ({ page, request }) => {
  // A month of Madrid prices around €100 and nothing older: a provisional Baseline.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fs-e2e-baseline-"));
  const prices = [1, 2, 3, 4, 5, 6].map((d) => ({
    origin: "HEL", destination: "MAD", depart_date: `2026-12-0${d}`, price: 100, airline: "IB",
  }));
  prices.push({ origin: "HEL", destination: "MAD", depart_date: "2026-12-10", price: 60, airline: "IB" });
  fs.writeFileSync(path.join(dir, "hel-mad-2026-12.json"), JSON.stringify({ currency: "EUR", prices }));
  const watch = await request.post("/api/watches", {
    data: {
      name: "Madrid band",
      origins: { include: [{ kind: "airport", code: "HEL" }] },
      destinations: { include: [{ kind: "airport", code: "MAD" }] },
      trip_pattern: { preset: "one_way_fixed", departure: "2026-12-10" },
      adults: 1,
      price_threshold: null,
    },
  });
  expect(watch.ok()).toBeTruthy();
  runPipeline("2026-10-20T07:00:00+00:00", dir);

  await page.goto("/routes");
  await page.getByRole("combobox", { name: "Route" }).fill("helsinki madrid");
  await page.getByRole("option", { name: /Helsinki HEL → Madrid MAD/ }).click();
  await expect(page.getByText("Showing")).toContainText("Helsinki HEL → Madrid MAD");
  await page.getByRole("group", { name: "Departs" }).getByRole("button", { name: "Thu 10 Dec" }).click();

  await expect(page.getByRole("img", { name: /HEL to MAD.*provisional Baseline €100/ })).toBeVisible();
  await expect(page.getByText("PROVISIONAL BASELINE €100")).toBeVisible();
  await expect(page.getByText(/Baseline ± MAD \(provisional/)).toBeVisible();
  await page.screenshot({ path: "test-results/route-explorer-baseline.png", fullPage: true });
});
