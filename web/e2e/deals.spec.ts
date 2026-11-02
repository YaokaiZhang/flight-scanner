// The Deals feed folds a Route's Deals behind one summary row.
import { expect, test } from "@playwright/test";

const deal = (id: number, over: object) => ({
  id, watch_id: 1, watch_name: "Southern Europe", origin: "HEL", destination: "BGY",
  origin_city: "Helsinki", destination_city: "Orio al Serio", return_date: null, adults: 2,
  price_total_eur: 200, source: "travelpayouts", observed_at: "2026-11-01T09:00:00Z",
  ticketing: "separate_tickets", verification: "unverified", verification_reason: null, verified_at: null,
  verified_price_total_eur: null, verified_price_per_adult_eur: null, baseline_tier: null,
  detected_at: "2026-11-01T09:00:00Z", airlines: null, stops: null, travel_minutes: null,
  separate_tickets: true, booking_url: "https://example.test/", baseline_per_adult_eur: null,
  pct_below_baseline: null, baseline: null, deal_context: null, feedback: null, ...over,
});

const DEALS = [
  deal(1, { destination: "VLC", destination_city: "Valencia", outbound_date: "2026-12-01", price_per_adult_eur: 90 }),
  deal(2, { outbound_date: "2026-12-12", return_date: "2026-12-17", price_per_adult_eur: 126.47 }),
  deal(3, { outbound_date: "2026-12-04", return_date: "2026-12-07", price_per_adult_eur: 107.99 }),
  // Failed: no longer on offer, so its low price and late date stay out of the summary.
  deal(4, { outbound_date: "2026-12-20", return_date: "2026-12-23", price_per_adult_eur: 50, verification: "failed" }),
];

test("a Route's Deals fold behind their dates and price range", async ({ page }) => {
  await page.route("**/api/deals*", (route) => route.fulfill({ json: DEALS }));
  await page.goto("/deals");

  const feed = page.getByRole("list", { name: "Deals", exact: true });
  await expect(page.getByText("on 2 routes")).toBeVisible();
  const route = feed.getByRole("button", { expanded: false });
  await expect(route).toContainText("Helsinki → Orio al Serio");
  await expect(route).toContainText("Out Fri 4 Dec – Sat 12 Dec");
  await expect(route).toContainText("Back Mon 7 Dec – Thu 17 Dec");
  await expect(route).toContainText("€107.99–€126.47/adult");
  await expect(route).toContainText("3 Deals");
  await expect(feed).not.toContainText("Sat 12 Dec → Thu 17 Dec");
  await page.screenshot({ path: "test-results/deals-folded.png", fullPage: true });

  // Sorted by Route: BGY first, and its earliest departure is what the inspector opens on.
  await expect(feed.getByRole("listitem").first()).toContainText("BGY");
  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector).toContainText("€107.99");
  await expect(inspector).toContainText("Helsinki → Orio al Serio");

  await route.click();
  const rows = page.getByRole("list", { name: "Deals HEL to BGY" }).getByRole("listitem");
  await expect(rows).toHaveCount(3);
  await rows.nth(1).getByRole("button").click();
  await expect(inspector).toContainText("€126.47");
  await expect(rows.nth(1).getByRole("button")).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: "test-results/deals-unfolded.png", fullPage: true });

  await feed.getByRole("button", { expanded: true }).click();
  await expect(rows).toHaveCount(0);

  // A Route with one Deal has nothing to fold.
  await expect(feed.getByRole("listitem").last()).toContainText("Valencia");
  await expect(feed.getByRole("listitem").last().getByRole("button")).not.toHaveAttribute("aria-expanded", /.*/);

  // The price range fits on a phone.
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(route).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: "test-results/deals-mobile.png" });
});
