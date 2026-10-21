"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Route, type RouteHistory } from "@/lib/api";
import { formatDate, formatEur, formatInstant } from "@/lib/format";
import { PriceHistoryChart } from "./PriceHistoryChart";

const ONE_WAY = "";

export function RouteExplorer() {
  const [routes, setRoutes] = useState<Route[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [routeKey, setRouteKey] = useState("");
  const [departure, setDeparture] = useState("");
  const [returnDate, setReturnDate] = useState(ONE_WAY);
  const [history, setHistory] = useState<RouteHistory | null>(null);

  useEffect(() => {
    api.listRoutes().then(
      (rs) => {
        setRoutes(rs);
        if (rs[0]) setRouteKey(`${rs[0].origin}-${rs[0].destination}`);
      },
      (e: ApiError) => setError(`Could not load routes (${e.status ?? "network"})`),
    );
  }, []);

  const route = routes?.find((r) => `${r.origin}-${r.destination}` === routeKey) ?? null;
  const departures = useMemo(() => {
    if (!route) return [];
    return [...new Set([...route.departure_dates, ...route.round_trips.map((t) => t.departure_date)])].sort();
  }, [route]);
  const returns = route?.round_trips.filter((t) => t.departure_date === departure).map((t) => t.return_date) ?? [];
  const hasLeg = route?.departure_dates.includes(departure) ?? false;

  // keep the selection valid as the route changes
  useEffect(() => {
    if (departures.length && !departures.includes(departure)) setDeparture(departures[0]);
  }, [departures, departure]);
  useEffect(() => {
    if (returnDate !== ONE_WAY && !returns.includes(returnDate)) setReturnDate(hasLeg ? ONE_WAY : returns[0] ?? ONE_WAY);
    if (returnDate === ONE_WAY && !hasLeg && returns.length) setReturnDate(returns[0]);
  }, [returns, returnDate, hasLeg]);

  useEffect(() => {
    if (!route || !departure) return;
    let live = true;
    api.routeHistory(route.origin, route.destination, departure, returnDate || undefined).then(
      (h) => live && setHistory(h),
      (e: ApiError) => live && setError(`Could not load price history (${e.status ?? "network"})`),
    );
    return () => {
      live = false;
    };
  }, [route, departure, returnDate]);

  const points = history?.points ?? [];
  const current = points.filter((p) => p.valid_to === null);
  const cheapestNow = current.length ? Math.min(...current.map((p) => p.price_per_adult_eur)) : null;
  const lowest = points.length ? Math.min(...points.map((p) => p.price_per_adult_eur)) : null;
  const observations = points.reduce((n, p) => n + p.observations, 0);
  const dates = history
    ? `${formatDate(history.departure_date)}${history.return_date ? ` → ${formatDate(history.return_date)}` : " · one way"}`
    : "";

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Route explorer</h1>
            <p className="lede">Price per adult over time · <b>one step per price change</b></p>
          </div>
          {routes && routes.length > 0 && (
            <div className="controls">
              <label className="field">
                <span>Route</span>
                <select className="input" value={routeKey} onChange={(e) => setRouteKey(e.target.value)}>
                  {routes.map((r) => (
                    <option key={`${r.origin}-${r.destination}`} value={`${r.origin}-${r.destination}`}>
                      {r.origin} → {r.destination}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Departs</span>
                <select className="input" value={departure} onChange={(e) => setDeparture(e.target.value)}>
                  {departures.map((d) => (
                    <option key={d} value={d}>{formatDate(d)}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Returns</span>
                <select className="input" value={returnDate} onChange={(e) => setReturnDate(e.target.value)}>
                  {hasLeg && <option value={ONE_WAY}>One way (Leg price)</option>}
                  {returns.map((r) => (
                    <option key={r} value={r}>{formatDate(r)} (Round-trip price)</option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {routes && routes.length === 0 && (
          <div className="empty"><strong>No price history yet</strong>Routes appear after the first scan.</div>
        )}
        {history && points.length === 0 && routes && routes.length > 0 && (
          <div className="empty"><strong>No prices for these dates</strong>Pick another departure.</div>
        )}
        {history && points.length > 0 && (
          <>
            <PriceHistoryChart
              points={points}
              label={`Price per adult, ${history.origin} to ${history.destination}, ${dates}: ${points.length} price ${points.length === 1 ? "level" : "levels"}${cheapestNow !== null ? `, now ${formatEur(cheapestNow)}` : ""}.`}
            />
            <h2 className="section-head">Price changes</h2>
            <div className="table-wrap">
              <table aria-label="Price changes">
                <thead>
                  <tr>
                    <th>From</th><th>Until</th><th>Source</th><th>Kind</th>
                    <th className="num">Seen</th><th className="num">Per adult</th>
                  </tr>
                </thead>
                <tbody>
                  {[...points].reverse().map((p) => (
                    <tr key={`${p.source}-${p.valid_from}`}>
                      <td data-label="From">{formatInstant(p.valid_from)}</td>
                      <td data-label="Until">{p.valid_to ? formatInstant(p.valid_to) : "now"}</td>
                      <td data-label="Source">{p.source}</td>
                      <td data-label="Kind">
                        {p.kind === "leg" ? "Leg price" : "Round-trip price"}
                        {p.airline ? ` · ${p.airline}` : ""}
                        {p.stops !== null ? ` · ${p.stops === 0 ? "direct" : `${p.stops} stop${p.stops > 1 ? "s" : ""}`}` : ""}
                      </td>
                      <td data-label="Seen" className="num">{p.observations}×</td>
                      <td data-label="Per adult" className="num">{formatEur(p.price_per_adult_eur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
      <aside className="inspector" aria-label="Inspector" aria-live="polite">
        {history && points.length > 0 ? (
          <>
            <section>
              <h2 className="widget-label">Route</h2>
              <div className="route-big">
                {history.origin}<span className="arrow">→</span>{history.destination}
              </div>
              <p className="meta">{dates}</p>
            </section>
            <section>
              <h2 className="widget-label">Price now</h2>
              {cheapestNow !== null ? (
                <div className="data-point">{formatEur(cheapestNow)}<small>/adult</small></div>
              ) : (
                <p className="meta">No current price.</p>
              )}
              <p className="data-desc">
                Lowest seen <em>{formatEur(lowest!)}</em> · {points.length} price{" "}
                {points.length === 1 ? "level" : "levels"} from {observations} observations.
              </p>
            </section>
            <section>
              <h2 className="widget-label">Evidence</h2>
              <p className="meta">
                Cached prices, EUR per adult. Repeated identical observations extend a row instead of
                adding one. No Baseline yet.
              </p>
            </section>
          </>
        ) : (
          <p className="meta">Choose a route and departure date.</p>
        )}
      </aside>
    </>
  );
}
