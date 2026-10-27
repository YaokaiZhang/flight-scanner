// Watch editor: Places with an Exclusion, the resolved airport count, edit, pause and delete.
import { expect, test } from "@playwright/test";

test("build a Region-minus-country Watch, then edit, pause and delete it", async ({ page }) => {
  await page.goto("/watches");
  const editor = page.getByRole("complementary", { name: "Watch editor" });
  await editor.getByLabel("Name").fill("Sun, not Sweden");
  await editor.getByRole("combobox", { name: "From" }).fill("HEL");
  await editor.getByRole("option", { name: /Helsinki Vantaa/ }).click();

  const to = editor.getByRole("combobox", { name: "To" });
  await to.fill("europe");
  await expect(editor.getByRole("option").first()).toContainText("Europe");
  await to.press("Enter"); // first suggestion: the Europe Region
  await to.fill("-sweden");
  await editor.getByRole("option", { name: /Sweden/ }).first().click();

  const chips = editor.getByRole("list", { name: "To Places" });
  await expect(chips.getByRole("listitem").filter({ hasText: "Europe" })).toContainText("region");
  await expect(chips.getByRole("listitem").filter({ hasText: "Sweden" })).toContainText("exclude");
  await expect(editor.getByText(/Resolves to [\d,]+ airports/)).toBeVisible();

  // The Region tree lists what Europe covers; Sweden is struck through as excluded.
  await editor.getByText("Region tree").click();
  await editor.locator(".tree li summary", { hasText: "Europe" }).first().click();
  await expect(editor.locator(".tree li.x", { hasText: "Sweden" })).toBeVisible();

  await editor.getByLabel("Departure date").fill("2026-11-14");
  await editor.getByRole("button", { name: "Create Watch" }).click();
  await expect(editor.getByRole("status")).toContainText("Saved");

  const row = page.getByRole("row").filter({ hasText: "Sun, not Sweden" });
  await expect(row).toContainText("Europe − Sweden");
  await row.getByRole("button", { name: "Edit Sun, not Sweden" }).click();
  await expect(editor.getByRole("heading", { name: "Edit Watch" })).toBeVisible();

  await editor.getByLabel("Name").fill("Sun, still not Sweden");
  await editor.getByRole("button", { name: "More adults" }).click();
  await editor.getByRole("button", { name: "Save Watch" }).click();
  const edited = page.getByRole("row").filter({ hasText: "Sun, still not Sweden" });
  await expect(edited.getByRole("button", { name: "Edit Sun, still not Sweden" })).toHaveText("Editing");
  await expect(edited.getByRole("cell").nth(3)).toHaveText("2"); // Adults column

  await editor.getByRole("button", { name: "Pause" }).click();
  await expect(edited).toContainText("paused");
  await editor.getByRole("button", { name: "Resume" }).click();
  await expect(edited).toContainText("active");

  await editor.getByRole("button", { name: "Delete" }).click();
  await editor.getByRole("button", { name: "Confirm delete" }).click();
  await expect(edited).toHaveCount(0);
  await page.screenshot({ path: "test-results/watch-editor.png", fullPage: true });
});
