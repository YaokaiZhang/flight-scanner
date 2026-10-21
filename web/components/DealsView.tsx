"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Deal } from "@/lib/api";
import { formatDate, formatEur, formatInstant } from "@/lib/format";

function VerificationTag({ deal }: { deal: Deal }) {
  return deal.verification === "verified" ? (
    <span className="tag verified">Verified</span>
  ) : (
    <span className="tag unverified">Unverified</span>
  );
}

function TicketingTag({ deal }: { deal: Deal }) {
  if (deal.ticketing === "separate_tickets") return <span className="tag plain">2 separate tickets</span>;
  if (deal.ticketing === "single_ticket") return <span className="tag plain">Single ticket</span>;
  return null;
}

export function DealsView() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    api.listDeals().then(
      (d) => {
        setDeals(d);
        setSelectedId(d[0]?.id ?? null);
      },
      (e: ApiError) => setError(`Could not load Deals (${e.status ?? "network"})`),
    );
  }, []);

  const selected = deals?.find((d) => d.id === selectedId) ?? null;

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Deals</h1>
            <p className="lede">{deals ? <><b>{deals.length}</b> {deals.length === 1 ? "Deal" : "Deals"}, newest first</> : "Loading"}</p>
          </div>
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {deals && deals.length === 0 && (
          <div className="empty"><strong>No Deals yet</strong>A quiet feed is the goal.</div>
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
                      <div className="tags"><VerificationTag deal={d} /><TicketingTag deal={d} /></div>
                    </div>
                    <div className="price">
                      <b>{formatEur(d.price_per_adult_eur)}<small>/adult</small></b>
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
              <div className="data-point">{formatEur(selected.price_total_eur)}<small>total</small></div>
              <p className="data-desc">
                <em>{formatEur(selected.price_per_adult_eur)}</em> per adult for {selected.adults} adult
                {selected.adults > 1 ? "s" : ""}. Under the Watch&apos;s Price threshold; no Baseline yet.
              </p>
            </section>
            <section>
              <h2 className="widget-label">Evidence</h2>
              <div className="tags"><VerificationTag deal={selected} /><TicketingTag deal={selected} /></div>
              <p className="meta">
                Seen by {selected.source} at {formatInstant(selected.observed_at)}. Cached price, not
                checked live.
              </p>
            </section>
          </>
        ) : (
          <p className="meta">Select a Deal to inspect it.</p>
        )}
      </aside>
    </>
  );
}
