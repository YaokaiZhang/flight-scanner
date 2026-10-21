// Smoke test (spec: "one Playwright smoke test of create Watch -> see Deal").
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

test("create a Watch in the UI, then see its Deal in the Deals feed", async ({ page }) => {
  await page.goto("/watches");
  await page.getByLabel("Name").fill("Barcelona weekend");
  await page.getByRole("combobox", { name: "From" }).fill("hel");
  await page.getByRole("option", { name: /Helsinki Vantaa Airport/ }).click();
  await page.getByRole("combobox", { name: "To" }).fill("bcn");
  await page.getByRole("option", { name: /BCN/ }).first().click();
  await expect(page.getByText("Resolves to 1 airport")).toHaveCount(2);
  await page.getByLabel("Departure (one way)").fill("2026-11-14");
  await page.getByLabel("Price threshold (EUR)").fill("120");
  await page.getByRole("button", { name: "Create Watch" }).click();
  await expect(page.getByRole("status")).toContainText("Saved");
  await expect(page.getByRole("cell", { name: "Barcelona weekend" })).toBeVisible();

  runPipeline("2026-10-21T09:00:00+00:00"); // the fake source reports HEL→BCN 14 Nov at €89

  await page.getByRole("link", { name: "Deals", exact: true }).click();
  const deal = page.getByRole("list", { name: "Deals" }).getByRole("listitem").first();
  await expect(deal).toContainText("HEL");
  await expect(deal).toContainText("BCN");
  await expect(deal).toContainText("€89");
  await expect(deal).toContainText("Unverified");
  await page.screenshot({ path: "test-results/deals-feed.png", fullPage: true });
});
