"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Backtest, type Outcome, type PastDeal, type WatchBacktest } from "@/lib/api";
import { formatDate, formatEur, formatInstant } from "@/lib/format";

// Plain words for each outcome; the order is the order of the bar segments.
const OUTCOMES: { key: Outcome; label: string }[] = [
  { key: "real_dip", label: "Bounced back" },
  { key: "stayed_low", label: "Stayed low" },
  { key: "pending", label: "Waiting" },
  { key: "inconclusive", label: "Departed" },
  { key: "unjudged", label: "No Baseline" },
];
const LABEL = Object.fromEntries(OUTCOMES.map((o) => [o.key, o.label])) as Record<Outcome, string>;

const pct = (p: number | null) => (p === null ? "—" : `${Math.round(p * 100)}%`);

/** One stacked bar of a Watch's Deals by outcome. */
function OutcomeBar({ w }: { w: WatchBacktest }) {
  if (!w.deals) return <span className="meta">No Deals yet</span>;
  return (
    <span
      className="outcome-bar"
      role="img"
      aria-label={OUTCOMES.filter((o) => w.outcomes[o.key]).map((o) => `${w.outcomes[o.key]} ${o.label.toLowerCase()}`).join(", ")}
    >
      {OUTCOMES.filter((o) => w.outcomes[o.key]).map((o) => (
        <span key={o.key} className={`seg-${o.key}`} style={{ flexGrow: w.outcomes[o.key] }} title={`${LABEL[o.key]}: ${w.outcomes[o.key]}`} />
      ))}
    </span>
  );
}

function Legend() {
  return (
    <ul className="outcome-legend" aria-hidden="true">
      {OUTCOMES.slice(0, 3).map((o) => (
        <li key={o.key}><span className={`swatch seg-${o.key}`} />{o.label}</li>
      ))}
    </ul>
  );
}

/** The Deal price, its Baseline and the highest price seen since, on one line. */
function PriceTrack({ d }: { d: PastDeal }) {
  const points = [d.price_per_adult_eur, d.baseline_per_adult_eur, d.highest_later_price_per_adult_eur].filter(
    (p): p is number => p !== null,
  );
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const at = (p: number) => (hi === lo ? 50 : 4 + ((p - lo) / (hi - lo)) * 92);
  const later = d.highest_later_price_per_adult_eur;
  return (
    <div className="track" aria-hidden="true">
      {later !== null && later > d.price_per_adult_eur && (
        <span className="track-rise" style={{ left: `${at(d.price_per_adult_eur)}%`, width: `${at(later) - at(d.price_per_adult_eur)}%` }} />
      )}
      {d.baseline_per_adult_eur !== null && (
        <span className="track-baseline" style={{ left: `${at(d.baseline_per_adult_eur)}%` }}>
          <small>{formatEur(d.baseline_per_adult_eur)}</small>
        </span>
      )}
      <span className="track-deal" style={{ left: `${at(d.price_per_adult_eur)}%` }}>
        <small>{formatEur(d.price_per_adult_eur)}</small>
      </span>
    </div>
  );
}

function Inspector({ w }: { w: WatchBacktest }) {
  const judged = w.outcomes.real_dip + w.outcomes.stayed_low;
  const most = Math.max(1, ...w.pct_below_baseline.buckets.map((b) => b.deals));
  return (
    <>
      <section>
        <h2 className="widget-label">Bounced back</h2>
        <div className="data-point">{pct(w.precision)}</div>
        <p className="data-desc">{judged ? <><em>{w.outcomes.real_dip}</em> of {judged}</> : "Needs a few days of later prices"}</p>
      </section>
      <section>
        <h2 className="widget-label">Alerts</h2>
        <div className="data-point">{w.alerts_per_week}<small>/ week</small></div>
        <p className="meta">Sensitivity {w.sensitivity_pct}%</p>
      </section>
      <section>
        <h2 className="widget-label">Below Baseline</h2>
        <table className="bars" aria-label="Deals by % below Baseline">
          <tbody>
            {w.pct_below_baseline.buckets.map((b) => (
              <tr key={b.from_pct}>
                <th scope="row">{b.to_pct === null ? `${b.from_pct}%+` : `${b.from_pct}–${b.to_pct}%`}</th>
                <td><span className="bar" style={{ width: `${(b.deals / most) * 100}%` }} /></td>
                <td className="num">{b.deals}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section>
        <h2 className="widget-label">Your ratings</h2>
        <p className="ratings"><span aria-label="Good">👍 {w.feedback.up}</span><span aria-label="Bad">👎 {w.feedback.down}</span></p>
      </section>
    </>
  );
}

export function BacktestView() {
  const [data, setData] = useState<Backtest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    api.backtest().then(
      (b) => {
        setData(b);
        setSelected((s) => s ?? b.watches.find((w) => w.deals > 0)?.watch_id ?? b.watches[0]?.watch_id ?? null);
      },
      (e: ApiError) => setError(`Could not load the backtest (${e.status ?? "network"})`),
    );
  }, []);

  const current = data?.watches.find((w) => w.watch_id === selected) ?? null;

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Backtest</h1>
            <p className="lede">
              Did prices bounce back after each Deal?
              {data?.computed_at ? ` · ${formatInstant(data.computed_at)}` : ""}
            </p>
          </div>
          <Legend />
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {data && data.watches.length === 0 && (
          <div className="empty"><strong>No Watches yet</strong>Create one to start collecting Deals.</div>
        )}
        {data && data.watches.length > 0 && (
          <div className="table-wrap">
            <table aria-label="Backtest per Watch">
              <thead>
                <tr><th>Watch</th><th>Deals</th><th className="num">Bounced back</th><th className="num">Alerts / week</th></tr>
              </thead>
              <tbody>
                {data.watches.map((w) => (
                  <tr
                    key={w.watch_id}
                    className={`selectable${w.status !== "active" ? " paused" : ""}`}
                    aria-selected={w.watch_id === selected}
                    onClick={() => setSelected(w.watch_id)}
                  >
                    <td className="row-title">
                      <button type="button" onClick={() => setSelected(w.watch_id)}>{w.watch_name}</button>
                      {w.deals > 0 && <div className="sub">{w.deals} Deal{w.deals === 1 ? "" : "s"}</div>}
                    </td>
                    <td data-label="Deals" className="bar-cell"><OutcomeBar w={w} /></td>
                    <td data-label="Bounced back" className="num">{pct(w.precision)}</td>
                    <td data-label="Alerts / week" className="num">{w.alerts_per_week}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {current && current.past_deals.length > 0 && (
          <>
            <div className="section-row">
              <h2 className="section-head">{current.watch_name}</h2>
              <ul className="track-legend" aria-hidden="true">
                <li><span className="key-deal" />Deal</li>
                <li><span className="key-baseline" />Baseline</li>
                <li><span className="key-rise" />Highest since</li>
              </ul>
            </div>
            <div className="table-wrap">
              <table aria-label="Past Deals">
                <thead>
                  <tr><th>Trip</th><th>Price per adult</th><th>Outcome</th><th><span className="sr-only">Rating</span></th></tr>
                </thead>
                <tbody>
                  {current.past_deals.map((d) => (
                    <tr key={d.deal_id}>
                      <td className="row-title">
                        {d.origin} → {d.destination}
                        <div className="sub">
                          {formatDate(d.outbound_date)}
                          {d.return_date ? ` → ${formatDate(d.return_date)}` : " · one way"}
                        </div>
                      </td>
                      <td data-label="Price per adult" className="track-cell">
                        <PriceTrack d={d} />
                        <span className="sr-only">
                          Deal {formatEur(d.price_per_adult_eur)}
                          {d.baseline_per_adult_eur !== null && `, Baseline ${formatEur(d.baseline_per_adult_eur)}`}
                          {d.highest_later_price_per_adult_eur !== null && `, highest since ${formatEur(d.highest_later_price_per_adult_eur)}`}
                        </span>
                      </td>
                      <td data-label="Outcome">
                        <span className={`outcome outcome-${d.outcome}`}>{LABEL[d.outcome]}</span>
                        {d.pct_below_baseline !== null && <div className="sub">−{d.pct_below_baseline}%</div>}
                      </td>
                      <td data-label="Rating" className="num">{d.rating === "up" ? "👍" : d.rating === "down" ? "👎" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
      <aside className="inspector" aria-label="Inspector" aria-live="polite">
        {current ? <Inspector w={current} /> : <p className="meta">Select a Watch.</p>}
      </aside>
    </>
  );
}
