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
  await page.getByLabel("From (airport)").fill("hel");
  await page.getByLabel("To (airport)").fill("bcn");
  await page.getByLabel("Departure (one way)").fill("2026-11-14");
  await page.getByLabel("Price threshold (EUR)").fill("120");
  await page.getByLabel("Email").uncheck(); // Telegram only
  await page.getByRole("button", { name: "Create Watch" }).click();
  await expect(page.getByRole("status")).toContainText("Saved");
  await expect(page.getByRole("cell", { name: "Barcelona weekend" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Telegram", exact: true })).toBeVisible();

  runPipeline("2026-10-21T09:00:00+00:00"); // the fake source reports HEL→BCN 14 Nov at €89

  await page.getByRole("link", { name: "Deals", exact: true }).click();
  const deal = page.getByRole("list", { name: "Deals" }).getByRole("listitem").first();
  await expect(deal).toContainText("HEL");
  await expect(deal).toContainText("BCN");
  await expect(deal).toContainText("€89");
  await expect(deal).toContainText("Unverified");

  // The inspector shows the Alert's details and a booking link; rate it 👍 and it sticks.
  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector).toContainText("VY · direct · 4 h 10 min");
  await expect(inspector.getByRole("link", { name: /Book this trip/ })).toHaveAttribute(
    "href", /google\.com\/travel\/flights/,
  );
  await inspector.getByRole("button", { name: "Good Alert" }).click();
  await expect(inspector.getByRole("button", { name: "Good Alert" })).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Good Alert" })).toHaveAttribute("aria-pressed", "true");

  await page.screenshot({ path: "test-results/deals-feed.png", fullPage: true });

  // Filter by status: nothing is Verified yet.
  await page.getByRole("group", { name: "Verification status" }).getByRole("button", { name: "verified", exact: true }).click();
  await expect(page.getByText("No verified Deals.")).toBeVisible();
});
