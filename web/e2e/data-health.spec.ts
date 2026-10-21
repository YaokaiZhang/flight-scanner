// Data-health page: source freshness, coverage gaps, backlog and a data-quality gate, via the API.
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repo = path.resolve(__dirname, "..", "..");
const python = process.env.FS_PYTHON ?? path.join(repo, ".venv", "bin", "python");

function runPipeline(at: Date, payloadDir: string) {
  execFileSync(
    python,
    [
      "-m", "flight_scanner.testing.e2e_stack", "scan",
      "--state-dir", process.env.FS_E2E_STATE_DIR!,
      "--payload-dir", payloadDir,
      "--at", at.toISOString(),
    ],
    { cwd: repo, stdio: "pipe", timeout: 120_000 },
  );
}

test("the data-health page shows sources, coverage gaps and a gate after an empty scan", async ({ page, request }) => {
  // the API's clock is the real one, so the scans happen now and depart in six weeks
  const now = new Date();
  const departure = new Date(now.getTime() + 42 * 86_400_000).toISOString().slice(0, 10);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fs-e2e-health-"));
  const file = path.join(dir, "hel-tll.json");
  fs.writeFileSync(
    file,
    JSON.stringify({
      currency: "EUR",
      prices: [{ origin: "HEL", destination: "TLL", depart_date: departure, price: 40 }],
    }),
  );
  const watch = await request.post("/api/watches", {
    data: {
      name: "Health check",
      origins: { include: [{ kind: "airport", code: "HEL" }] },
      destinations: { include: [{ kind: "airport", code: "TLL" }, { kind: "airport", code: "RIX" }] },
      trip_pattern: { preset: "one_way_fixed", departure },
      adults: 1,
      price_threshold: null,
    },
  });
  expect(watch.ok()).toBeTruthy();
  const watchId = (await watch.json()).id;
  runPipeline(now, dir);

  await page.goto("/data-health");
  await expect(page.getByRole("heading", { name: "Data health" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Sources" }).getByRole("row", { name: /fake/ })).toContainText("Healthy");
  await expect(page.getByRole("table", { name: "Coverage gaps" })).toContainText("HEL → RIX");
  await expect(page.getByRole("table", { name: "Scan backlog" })).toContainText("fake");
  await expect(page.getByText("No gate in force")).toBeVisible();

  // HEL suddenly answers with nothing: its prices are gated until it answers again
  fs.writeFileSync(file, JSON.stringify({ currency: "EUR", prices: [] }));
  runPipeline(new Date(now.getTime() + 60_000), dir);

  await page.reload();
  const gates = page.getByRole("table", { name: "Data-quality gates" });
  await expect(gates).toContainText("Empty scan");
  await expect(gates).toContainText("fake · HEL");
  await expect(page.getByRole("table", { name: "Sources" }).getByRole("row", { name: /fake/ })).toContainText("Gated");
  await expect(page.getByRole("complementary", { name: "Inspector" })).toContainText("Recent check failures");
  await page.screenshot({ path: "test-results/data-health.png", fullPage: true });
  expect((await request.delete(`/api/watches/${watchId}`)).ok()).toBeTruthy(); // later specs scan in the past
});
