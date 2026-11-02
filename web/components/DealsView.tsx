"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Deal, type DealStatus, type Rating, type Watch } from "@/lib/api";
import { formatDate, formatEur, formatInstant, formatMinutes, formatStops } from "@/lib/format";

const ICONS = {
  check: "M3 8.5l3 3 7-7",
  chevron: "M6 3l5 5-5 5",
  out: "M6 3H3v10h10v-3M9 3h4v4M13 3L7 9",
  up: "M5 14V7l3-5c1.2 0 1.8.8 1.6 2L9 7h3.6c.9 0 1.5.8 1.3 1.6l-1.2 4.2c-.2.7-.8 1.2-1.5 1.2H5zM2 7h3v7H2z",
  down: "M11 2v7l-3 5c-1.2 0-1.8-.8-1.6-2L7 9H3.4c-.9 0-1.5-.8-1.3-1.6l1.2-4.2C3.5 2.5 4.1 2 4.8 2H11zM14 9h-3V2h3z",
  tickets: "M2 5h7v6H2zM7 3h7v6h-3",
  x: "M4 4l8 8M12 4l-8 8",
} as const;

function Icon({ name }: { name: keyof typeof ICONS | "dash" }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" aria-hidden="true">
      {name === "dash" ? <circle cx="8" cy="8" r="5.5" strokeDasharray="2 2" /> : <path d={ICONS[name]} />}
    </svg>
  );
}

function StatusTags({ deal }: { deal: Deal }) {
  return (
    <>
      {deal.verification === "verified" ? (
        <span className="tag verified"><Icon name="check" />Verified</span>
      ) : deal.verification === "failed" ? (
        <span className="tag fail"><Icon name="x" />Failed check</span>
      ) : (
        <span className="tag unverified"><Icon name="dash" />Unverified</span>
      )}
      {deal.ticketing === "separate_tickets" && <span className="tag plain"><Icon name="tickets" />2 separate tickets</span>}
      {deal.ticketing === "single_ticket" && <span className="tag plain">Single ticket</span>}
    </>
  );
}

const flightFacts = (d: Deal) =>
  [
    d.airlines,
    d.stops !== null ? formatStops(d.stops) : null,
    d.travel_minutes !== null ? formatMinutes(d.travel_minutes) : null,
  ].filter(Boolean).join(" · ");

const STATUSES: (DealStatus | "all")[] = ["all", "verified", "unverified", "failed"];

// A Verified Deal is priced by its live check (exact for the Watch's adults); others by the cache.
const perAdult = (d: Deal) =>
  d.verification === "verified" && d.verified_price_per_adult_eur !== null ? d.verified_price_per_adult_eur : d.price_per_adult_eur;
const total = (d: Deal) =>
  d.verification === "verified" && d.verified_price_total_eur !== null ? d.verified_price_total_eur : d.price_total_eur;

const TIER_NAMES: Record<string, string> = { price_insight: "Price insight" };
const tierName = (tier: string) => TIER_NAMES[tier] ?? `${tier} tier`;

function verificationText(d: Deal): string {
  const adults = `${d.adults} adult${d.adults > 1 ? "s" : ""}`;
  const at = d.verified_at ? ` at ${formatInstant(d.verified_at)}` : "";
  const live = d.verified_price_total_eur !== null ? `${formatEur(d.verified_price_total_eur)} for ${adults}` : null;
  if (d.verification === "verified") return `Checked live on Google Flights${at}: ${live ?? adults}.`;
  if (d.verification === "failed") {
    return d.verification_reason === "not_found"
      ? `Checked live${at}: not found for ${adults}. Not alerted.`
      : `Checked live${at}: ${live ?? "price"} is no longer a Deal. Not alerted.`;
  }
  const cached = `Seen by ${d.source} at ${formatInstant(d.observed_at)}. Cached price, not checked live; confirm before booking.`;
  if (d.verification_reason === "budget_exhausted") return `Verification budget spent. ${cached}`;
  if (d.verification_reason === "verifier_error") return `Live check unavailable. ${cached}`;
  return cached;
}

const cities = (d: Deal) => `${d.origin_city ?? d.origin} → ${d.destination_city ?? d.destination}`;

type RouteGroup = { key: string; deals: Deal[] };

// Routes A to Z by airport code; within a Route, earliest departure first.
function groupByRoute(deals: Deal[]): RouteGroup[] {
  const groups = new Map<string, Deal[]>();
  for (const d of deals) {
    const key = `${d.origin}-${d.destination}`;
    groups.set(key, [...(groups.get(key) ?? []), d]);
  }
  const byTrip = (a: Deal, b: Deal) =>
    a.outbound_date.localeCompare(b.outbound_date) || (a.return_date ?? "").localeCompare(b.return_date ?? "");
  return [...groups]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, ds]) => ({ key, deals: ds.sort(byTrip) }));
}

const dateSpan = (dates: string[]) => {
  const sorted = [...new Set(dates)].sort();
  const [first, last] = [sorted[0], sorted[sorted.length - 1]];
  return first === last ? formatDate(first) : `${formatDate(first)} – ${formatDate(last)}`;
};

// A failed Deal is no longer on offer, so it only counts if the whole Route failed.
function RouteRow({ group, open, selected, onToggle }: { group: RouteGroup; open: boolean; selected: boolean; onToggle: () => void }) {
  const [head] = group.deals;
  const live = group.deals.filter((d) => d.verification !== "failed");
  const counted = live.length > 0 ? live : group.deals;
  const prices = counted.map(perAdult);
  const [low, high] = [Math.min(...prices), Math.max(...prices)];
  const returns = counted.flatMap((d) => d.return_date ?? []);
  const watchNames = [...new Set(group.deals.map((d) => d.watch_name))];
  const verified = group.deals.filter((d) => d.verification === "verified").length;
  return (
    <button className={`deal-row route-row${selected ? " has-selected" : ""}`} aria-expanded={open} onClick={onToggle}>
      <div>
        <div className="route">
          <span className="fold"><Icon name="chevron" /></span>
          {head.origin}<span className="arrow" aria-label="to">→</span>{head.destination}
        </div>
        <div className="sub cities">{cities(head)}</div>
        <div className="sub">{watchNames.length === 1 ? watchNames[0] : `${watchNames.length} Watches`}</div>
      </div>
      <div>
        <div className="when">Out {dateSpan(counted.map((d) => d.outbound_date))}</div>
        {returns.length > 0 && <div className="when">Back {dateSpan(returns)}</div>}
        <div className="tags">
          <span className="tag plain">{group.deals.length} Deals</span>
          {verified > 0 && <span className="tag verified"><Icon name="check" />{verified} verified</span>}
        </div>
      </div>
      <div className="price">
        <b className={low === high ? undefined : "span"}>
          {low === high ? formatEur(low) : `${formatEur(low)}–${formatEur(high)}`}<small>/adult</small>
        </b>
      </div>
    </button>
  );
}

function DealRow({ deal: d, selected, nested, onSelect }: { deal: Deal; selected: boolean; nested?: boolean; onSelect: () => void }) {
  return (
    <button className="deal-row" aria-pressed={selected} onClick={onSelect}>
      <div>
        {!nested && (
          <>
            <div className="route">
              {d.origin}<span className="arrow" aria-label="to">→</span>{d.destination}
            </div>
            <div className="sub cities">{cities(d)}</div>
          </>
        )}
        <div className="sub">{d.watch_name}</div>
      </div>
      <div>
        <div className="when">
          {formatDate(d.outbound_date)}
          {d.return_date ? ` → ${formatDate(d.return_date)}` : " · one way"}
        </div>
        <div className="tags"><StatusTags deal={d} /></div>
      </div>
      <div className="price">
        <b>{formatEur(perAdult(d))}<small>/adult</small></b>
        {d.baseline_per_adult_eur !== null && <span className="sub">base {formatEur(d.baseline_per_adult_eur)}</span>}
        {d.adults > 1 && <span className="sub">{formatEur(total(d))} total</span>}
      </div>
    </button>
  );
}

export function DealsView() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [status, setStatus] = useState<DealStatus | "all">("all");
  const [watchId, setWatchId] = useState<number | null>(null);
  const [rateError, setRateError] = useState<string | null>(null);
  const [openRoutes, setOpenRoutes] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.listWatches().then(setWatches, () => setWatches([]));
  }, []);

  useEffect(() => {
    let live = true;
    api.listDeals({ watchId: watchId ?? undefined, status: status === "all" ? undefined : status }).then(
      (d) => {
        if (!live) return;
        setDeals(d);
        setError(null);
        setSelectedId((cur) => (d.some((x) => x.id === cur) ? cur : (groupByRoute(d)[0]?.deals[0].id ?? null)));
      },
      (e: ApiError) => live && setError(`Could not load Deals (${e.status ?? "network"})`),
    );
    return () => {
      live = false;
    };
  }, [status, watchId]);

  const selected = deals?.find((d) => d.id === selectedId) ?? null;
  const groups = groupByRoute(deals ?? []);

  function toggleRoute(group: RouteGroup) {
    const opening = !openRoutes.has(group.key);
    const next = new Set(openRoutes);
    if (opening) next.add(group.key);
    else next.delete(group.key);
    setOpenRoutes(next);
    // Keep the inspector on a Deal the feed is showing.
    if (opening && !group.deals.some((d) => d.id === selectedId)) setSelectedId(group.deals[0].id);
  }
  const filtered = status !== "all" || watchId !== null;
  const watchName = watches.find((w) => w.id === watchId)?.name;

  async function rate(deal: Deal, rating: Rating) {
    const next = deal.feedback?.rating === rating ? null : rating; // pressing again clears it
    setRateError(null);
    try {
      const updated = await api.rateDeal(deal.id, next);
      setDeals((ds) => ds?.map((d) => (d.id === updated.id ? updated : d)) ?? ds);
    } catch (e) {
      setRateError(`Could not save the rating (${e instanceof ApiError ? e.status : "network"}).`);
    }
  }

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Deals</h1>
            <p className="lede">{deals ? <><b>{deals.length}</b> {deals.length === 1 ? "Deal" : "Deals"} on {groups.length} {groups.length === 1 ? "route" : "routes"}</> : "Loading"}</p>
          </div>
          <div className="controls">
            <div className="seg" role="group" aria-label="Verification status">
              {STATUSES.map((s) => (
                <button key={s} type="button" aria-pressed={status === s} onClick={() => setStatus(s)}>{s}</button>
              ))}
            </div>
            <label className="field">
              <span className="sr-only">Watch</span>
              <select
                className="input"
                aria-label="Watch"
                value={watchId ?? ""}
                onChange={(e) => setWatchId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">All Watches</option>
                {watches.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </label>
          </div>
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {deals && deals.length === 0 && (
          filtered ? (
            <div className="empty">
              <strong>No {status === "all" ? "" : `${status} `}Deals{watchName ? ` for ${watchName}` : ""}.</strong>
              Change the filters to see other Deals.
            </div>
          ) : (
            <div className="empty"><strong>No Deals yet</strong>A quiet feed is the goal.</div>
          )
        )}
        {deals && deals.length > 0 && (
          <>
            <div className="scale-head" aria-hidden="true">
              <span>Route</span><span>Dates</span><span className="num">Price</span>
            </div>
            <ul className="deal-list" aria-label="Deals">
              {groups.map((g) => {
                const hasSelected = g.deals.some((d) => d.id === selectedId);
                if (g.deals.length === 1) {
                  const [d] = g.deals;
                  return (
                    <li key={g.key}>
                      <DealRow deal={d} selected={d.id === selectedId} onSelect={() => setSelectedId(d.id)} />
                    </li>
                  );
                }
                const open = openRoutes.has(g.key);
                return (
                  <li key={g.key}>
                    <RouteRow group={g} open={open} selected={hasSelected && !open} onToggle={() => toggleRoute(g)} />
                    {open && (
                      <ul className="route-deals" aria-label={`Deals ${g.deals[0].origin} to ${g.deals[0].destination}`}>
                        {g.deals.map((d) => (
                          <li key={d.id}>
                            <DealRow deal={d} nested selected={d.id === selectedId} onSelect={() => setSelectedId(d.id)} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </main>
      <aside className="inspector" aria-label="Inspector" aria-live="polite">
        {selected ? (
          <>
            <section>
              <h2 className="widget-label">Route</h2>
              <div className="route-big">
                {selected.origin}<span className="arrow">→</span>{selected.destination}
              </div>
              <p className="meta">{cities(selected)}</p>
              <p className="meta">{selected.watch_name}</p>
            </section>
            <section>
              <h2 className="widget-label">Price</h2>
              <div className="data-point">{formatEur(perAdult(selected))}<small>per adult</small></div>
              <p className="data-desc">
                <em>{formatEur(total(selected))}</em> total for {selected.adults} adult
                {selected.adults > 1 ? "s" : ""} · {selected.return_date ? "round trip" : "one way"}
                {selected.return_date ? ` · ${selected.separate_tickets ? "2 separate tickets" : "single ticket"}` : ""}
              </p>
            </section>
            <section>
              <h2 className="widget-label">Against Baseline</h2>
              {selected.baseline_per_adult_eur !== null && selected.pct_below_baseline !== null ? (
                <>
                  <div className={`data-point${selected.baseline_tier === "provisional" ? " amber" : ""}`}>
                    −{selected.pct_below_baseline}<small>%</small>
                  </div>
                  <p className="data-desc">
                    Baseline <em>{formatEur(selected.baseline_per_adult_eur)}</em>
                    {selected.baseline_tier ? ` · ${tierName(selected.baseline_tier)}` : ""}
                    {selected.baseline?.observations != null && selected.baseline.observation_days != null
                      ? ` · ${selected.baseline.observations} obs over ${selected.baseline.observation_days} days`
                      : ""}
                  </p>
                </>
              ) : (
                <p className="data-desc">No Baseline yet: under the Watch&apos;s Price threshold.</p>
              )}
            </section>
            {selected.deal_context && (
              <section>
                <h2 className="widget-label">Why cheap?</h2>
                <p className="data-desc">{selected.deal_context}</p>
                <p className="meta">Deal context from web research. Not a price source.</p>
              </section>
            )}
            {flightFacts(selected) && (
              <section>
                <h2 className="widget-label">Itinerary</h2>
                <p className="data-desc">{flightFacts(selected)}</p>
              </section>
            )}
            <section>
              <h2 className="widget-label">Verification</h2>
              <div className="tags"><StatusTags deal={selected} /></div>
              <p className="data-desc">{verificationText(selected)}</p>
              <a className="btn-marker primary book" href={selected.booking_url} target="_blank" rel="noopener noreferrer">
                Book this trip <Icon name="out" />
              </a>
              <div className="actions rate" role="group" aria-label="Rate this Alert">
                <span className="field-label">Rate this Alert</span>
                <span className="spacer" />
                <button
                  type="button"
                  className="btn-icon"
                  aria-pressed={selected.feedback?.rating === "up"}
                  aria-label="Good Alert"
                  onClick={() => rate(selected, "up")}
                >
                  <Icon name="up" />
                </button>
                <button
                  type="button"
                  className="btn-icon"
                  aria-pressed={selected.feedback?.rating === "down"}
                  aria-label="Bad Alert"
                  onClick={() => rate(selected, "down")}
                >
                  <Icon name="down" />
                </button>
              </div>
              {selected.feedback && (
                <p className="meta">Rated {selected.feedback.rating === "up" ? "👍" : "👎"} from {selected.feedback.via === "telegram" ? "Telegram" : "the Deals feed"}.</p>
              )}
              {rateError && <p className="error" role="alert">{rateError}</p>}
            </section>
          </>
        ) : (
          <p className="meta">Select a Deal to inspect it.</p>
        )}
      </aside>
    </>
  );
}
