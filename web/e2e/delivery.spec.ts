// The Watch editor offers immediate Alerts or a daily Digest (ticket 07).
import { expect, test } from "@playwright/test";

test("a Watch created with Daily Digest is stored in Digest mode", async ({ page, request }) => {
  await page.goto("/watches");
  await page.getByLabel("Name").fill("Low priority Lisbon");
  await page.getByRole("combobox", { name: "From" }).fill("hel");
  await page.getByRole("option", { name: /Helsinki Vantaa Airport/ }).click();
  await page.getByRole("combobox", { name: "To" }).fill("lis");
  await page.getByRole("option", { name: /LIS/ }).first().click();
  await page.getByLabel("Departure date").fill("2026-11-20");
  await page.getByLabel("Daily Digest").check();
  await page.getByRole("button", { name: "Create Watch" }).click();
  await expect(page.getByRole("status")).toContainText("Saved");

  const watches = await (await request.get("/api/watches")).json();
  const lisbon = watches.find((w: { name: string }) => w.name === "Low priority Lisbon");
  expect(lisbon.delivery).toBe("digest");
});
