"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Deal, type DealStatus, type Rating, type Watch } from "@/lib/api";
import { formatDate, formatEur, formatInstant, formatMinutes, formatStops } from "@/lib/format";

const ICONS = {
  check: "M3 8.5l3 3 7-7",
  out: "M6 3H3v10h10v-3M9 3h4v4M13 3L7 9",
  up: "M5 14V7l3-5c1.2 0 1.8.8 1.6 2L9 7h3.6c.9 0 1.5.8 1.3 1.6l-1.2 4.2c-.2.7-.8 1.2-1.5 1.2H5zM2 7h3v7H2z",
  down: "M11 2v7l-3 5c-1.2 0-1.8-.8-1.6-2L7 9H3.4c-.9 0-1.5-.8-1.3-1.6l1.2-4.2C3.5 2.5 4.1 2 4.8 2H11zM14 9h-3V2h3z",
  tickets: "M2 5h7v6H2zM7 3h7v6h-3",
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

const STATUSES: (DealStatus | "all")[] = ["all", "verified", "unverified"];

export function DealsView() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [status, setStatus] = useState<DealStatus | "all">("all");
  const [watchId, setWatchId] = useState<number | null>(null);
  const [rateError, setRateError] = useState<string | null>(null);

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
        setSelectedId((cur) => (d.some((x) => x.id === cur) ? cur : (d[0]?.id ?? null)));
      },
      (e: ApiError) => live && setError(`Could not load Deals (${e.status ?? "network"})`),
    );
    return () => {
      live = false;
    };
  }, [status, watchId]);

  const selected = deals?.find((d) => d.id === selectedId) ?? null;
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
            <p className="lede">{deals ? <><b>{deals.length}</b> {deals.length === 1 ? "Deal" : "Deals"}, newest first</> : "Loading"}</p>
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
              {deals.map((d) => (
                <li key={d.id}>
                  <button
                    className="deal-row"
                    aria-pressed={d.id === selectedId}
                    onClick={() => setSelectedId(d.id)}
                  >
                    <div>
                      <div className="route">
                        {d.origin}<span className="arrow" aria-label="to">→</span>{d.destination}
                      </div>
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
                      <b>{formatEur(d.price_per_adult_eur)}<small>/adult</small></b>
                      {d.baseline_per_adult_eur !== null && <span className="sub">base {formatEur(d.baseline_per_adult_eur)}</span>}
                      {d.adults > 1 && <span className="sub">{formatEur(d.price_total_eur)} total</span>}
                    </div>
                  </button>
                </li>
              ))}
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
              <p className="meta">{selected.watch_name}</p>
            </section>
            <section>
              <h2 className="widget-label">Price</h2>
              <div className="data-point">{formatEur(selected.price_per_adult_eur)}<small>per adult</small></div>
              <p className="data-desc">
                <em>{formatEur(selected.price_total_eur)}</em> total for {selected.adults} adult
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
                    {selected.baseline_tier ? ` · ${selected.baseline_tier} tier` : ""}
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
              <h2 className="widget-label">{selected.verification === "verified" ? "Verified" : "Unverified"}</h2>
              <div className="tags"><StatusTags deal={selected} /></div>
              <p className="data-desc">
                {selected.verification === "verified"
                  ? `Checked live for ${selected.adults} adult${selected.adults > 1 ? "s" : ""}.`
                  : `Seen by ${selected.source} at ${formatInstant(selected.observed_at)}. Cached price, not checked live; confirm before booking.`}
              </p>
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
