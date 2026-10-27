// Watch assistant: the robot opens the side chat, a starter prompt gets a reply with proposals,
// Create posts the proposed spec, and Edit opens it prefilled in the Watch editor.
// The agent endpoints are stubbed (the real one calls Claude); Watches go to the e2e API.
import { expect, test, type Route } from "@playwright/test";

const iso = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);

const helsinki = { kind: "airport", code: "HEL", name: "Helsinki Vantaa", context: "Finland", airport_count: 1 } as const;
const barcelona = { kind: "airport", code: "BCN", name: "Barcelona El Prat", context: "Spain", airport_count: 1 } as const;
const malaga = { kind: "airport", code: "AGP", name: "Malaga", context: "Spain", airport_count: 1 } as const;

function proposal(id: string, name: string, destination: typeof barcelona | typeof malaga) {
  return {
    id,
    reason: `Weekends in ${destination.context} stay warm into December.`,
    spec: {
      name,
      origins: { include: [{ kind: "airport", code: "HEL" }] },
      destinations: { include: [{ kind: destination.kind, code: destination.code }] },
      trip_pattern: { preset: "rolling", within_days: 60, stay_nights: { min: 2, max: 4 } },
      adults: 2,
      price_threshold: { amount_eur: 300, basis: "per_adult" },
      channels: ["email", "telegram"],
    },
    places: [helsinki, destination],
    trip: {
      kind: "round_trip",
      rolling: true,
      departure_start: iso(0),
      departure_end: iso(60),
      stay_nights: { min: 2, max: 4 },
      return_by: null,
      latest_return: iso(64),
      trip_count: 183,
      expired: false,
    },
    resolved: { origins: 1, destinations: 1 },
  };
}

test("the robot proposes Watches that can be created or edited", async ({ page }) => {
  const stamp = Date.now().toString(36);
  const toCreate = proposal("p1", `Warm weekends ${stamp}`, barcelona);
  const toEdit = proposal("p2", `Malaga escape ${stamp}`, malaga);

  const asked: string[] = [];
  await page.route("**/api/agent", (route: Route) => route.fulfill({ json: { enabled: true } }));
  await page.route("**/api/agent/chats", async (route: Route) => {
    asked.push(route.request().postDataJSON().text);
    await new Promise((r) => setTimeout(r, 600)); // long enough to see the thinking state
    await route.fulfill({
      json: { chat_id: 7, reply: "Two ideas for warm long weekends:", proposals: [toCreate, toEdit] },
    });
  });

  await page.goto("/deals");
  const robot = page.getByRole("button", { name: "Watch assistant", exact: true });
  await expect(robot).toHaveAttribute("aria-expanded", "false");
  await robot.click();
  await expect(robot).toHaveAttribute("aria-expanded", "true");
  const drawer = page.getByRole("dialog", { name: "Watch assistant" });
  await expect(drawer.getByRole("textbox", { name: "Message the Watch assistant" })).toBeFocused();

  await drawer.getByRole("button", { name: "Long weekends somewhere warm this winter" }).click();
  await expect(drawer.getByText("Thinking")).toBeVisible();
  await expect(drawer.getByText("Two ideas for warm long weekends:")).toBeVisible();
  expect(asked).toEqual(["Long weekends somewhere warm this winter"]);

  const sheet = drawer.getByRole("article", { name: toCreate.spec.name });
  await expect(sheet).toContainText("Helsinki Vantaa→Barcelona El Prat");
  await expect(sheet).toContainText("183 trips");
  await expect(sheet).toContainText("€300 /adult");

  const posted = page.waitForRequest((r) => r.url().endsWith("/api/watches") && r.method() === "POST");
  await sheet.getByRole("button", { name: "Create" }).click();
  expect((await posted).postDataJSON()).toEqual(toCreate.spec);
  await expect(sheet.getByText("Created")).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Create" })).toHaveCount(0);
  await expect(sheet.getByRole("link", { name: "See it in Watches" })).toHaveAttribute("href", "/watches");

  // The conversation survives a reload.
  await page.reload();
  await robot.click();
  await expect(drawer.getByRole("article", { name: toCreate.spec.name })).toContainText("Created");

  // Edit hands the spec to the Watch editor on /watches.
  await drawer.getByRole("article", { name: toEdit.spec.name }).getByRole("button", { name: "Edit" }).click();
  await expect(page).toHaveURL(/\/watches$/);
  await expect(drawer).toHaveCount(0);
  const editor = page.getByRole("complementary", { name: "Watch editor" });
  await expect(editor.getByRole("heading", { name: "New Watch" })).toBeVisible();
  await expect(editor.getByLabel("Name")).toHaveValue(toEdit.spec.name);
  await expect(editor.getByRole("list", { name: "To Places" })).toContainText("Malaga");
  // The Watch created from the first sheet is listed.
  await expect(page.getByRole("row").filter({ hasText: toCreate.spec.name })).toBeVisible();

  await editor.getByRole("button", { name: "Create Watch" }).click();
  await expect(editor.getByRole("status")).toContainText("Saved");
  await expect(page.getByRole("row").filter({ hasText: toEdit.spec.name })).toContainText("2–4 nights");

  // Dismiss hides a sheet; Esc closes the drawer and returns focus to the robot.
  await robot.click();
  await drawer.getByRole("article", { name: toCreate.spec.name }).waitFor();
  await drawer.getByRole("article", { name: toEdit.spec.name }).getByRole("button", { name: "Dismiss" }).click();
  await expect(drawer.getByRole("article", { name: toEdit.spec.name })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(robot).toBeFocused();
});

test("the drawer explains when the assistant is off", async ({ page }) => {
  await page.route("**/api/agent", (route: Route) => route.fulfill({ json: { enabled: false } }));
  await page.goto("/watches");
  await page.getByRole("button", { name: "Watch assistant", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Watch assistant" });
  await expect(drawer.getByText(/The assistant is off/)).toBeVisible();
  await expect(drawer.getByRole("textbox", { name: "Message the Watch assistant" })).toBeDisabled();
});
