"use client";

// Route explorer: find a route by typing a city, airport or country, pick its dates from chips,
// and see the route's change-only price history.

import { useEffect, useId, useMemo, useState, type KeyboardEvent } from "react";
import { api, ApiError, type Route, type RouteHistory } from "@/lib/api";
import { formatDate, formatEur, formatInstant } from "@/lib/format";
import { PriceHistoryChart } from "./PriceHistoryChart";

const ONE_WAY = "";
const SHOWN_MATCHES = 40;

const keyOf = (r: Route) => `${r.origin}-${r.destination}`;
const fold = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
const dateCount = (r: Route) => r.departure_dates.length + r.round_trips.length;
const monthFmt = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });
const nightsBetween = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);

/** Every typed word must match one end of the route; the first word matching the origin ranks first. */
function rank(r: Route, words: string[]): number | null {
  const from = fold(`${r.origin} ${r.origin_city ?? ""} ${r.origin_airport ?? ""} ${r.origin_country ?? ""}`);
  const to = fold(`${r.destination} ${r.destination_city ?? ""} ${r.destination_airport ?? ""} ${r.destination_country ?? ""}`);
  if (!words.every((w) => from.includes(w) || to.includes(w))) return null;
  return words.length && from.includes(words[0]) ? 0 : 1;
}

function End({ code, city }: { code: string; city: string | null }) {
  return (
    <>
      {city ?? code} <span className="opt-code">{code}</span>
    </>
  );
}

function RouteSearch({ routes, onPick }: { routes: Route[]; onPick: (r: Route) => void }) {
  const id = useId();
  const listId = `${id}-list`;
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const words = fold(text).split(/[\s,→>]+/).filter(Boolean);
    return routes
      .map((r) => ({ r, rank: rank(r, words) }))
      .filter((m): m is { r: Route; rank: number } => m.rank !== null)
      .sort((a, b) => a.rank - b.rank || dateCount(b.r) - dateCount(a.r))
      .map((m) => m.r);
  }, [routes, text]);
  const shown = matches.slice(0, SHOWN_MATCHES);

  function pick(r: Route) {
    onPick(r);
    setText("");
    setOpen(false);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (shown.length ? (i + step + shown.length) % shown.length : 0));
    } else if (e.key === "Enter" && open && shown[active]) {
      e.preventDefault();
      pick(shown[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="field route-search">
      <label className="field-label" htmlFor={id}>Route</label>
      <div className="combo">
        <input
          id={id}
          className="input"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && shown.length ? `${listId}-${active}` : undefined}
          autoComplete="off"
          placeholder="Type a city, airport or country, e.g. Helsinki Barcelona"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKey}
        />
        {open && (
          <ul className="options" role="listbox" id={listId} aria-label="Matching routes">
            {shown.map((r, i) => (
              <li
                key={keyOf(r)}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(r)}
              >
                <span className="opt-name">
                  <End code={r.origin} city={r.origin_city} /> → <End code={r.destination} city={r.destination_city} />
                </span>
                <span className="opt-meta">
                  {r.origin_airport ?? r.origin}, {r.origin_country ?? "?"} → {r.destination_airport ?? r.destination},{" "}
                  {r.destination_country ?? "?"}
                </span>
                <span className="opt-meta">
                  {dateCount(r)} {dateCount(r) === 1 ? "trip" : "trips"} with prices
                </span>
              </li>
            ))}
            {matches.length === 0 && <li className="opt-none" role="presentation">No route matches “{text}”</li>}
            {matches.length > shown.length && (
              <li className="opt-none" role="presentation">
                {matches.length - shown.length} more: keep typing to narrow down
              </li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}

type Choice = { value: string; text: string; note?: string; group?: string };

/** A row of toggle chips (one per date), split into labelled rows when the choices have groups. */
function ChoiceChips({ label, choices, value, onChange }: { label: string; choices: Choice[]; value: string; onChange: (v: string) => void }) {
  const id = useId();
  const groups: [string, Choice[]][] = [];
  for (const c of choices) {
    const last = groups[groups.length - 1];
    if (last && last[0] === (c.group ?? "")) last[1].push(c);
    else groups.push([c.group ?? "", [c]]);
  }
  return (
    <div className="field">
      <span className="field-label" id={id}>{label}</span>
      <div className="pick-rows" role="group" aria-labelledby={id}>
        {groups.map(([group, cs]) => (
          <div className="pick-row" key={group}>
            {group && <span className="pick-group" aria-hidden="true">{group}</span>}
            {cs.map((c) => (
              <button key={c.value} type="button" className="pick" aria-pressed={c.value === value} onClick={() => onChange(c.value)}>
                {c.text}
                {c.note && <small>{c.note}</small>}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

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
        // start on the route with the most price history
        const busiest = rs.reduce<Route | null>((best, r) => (!best || dateCount(r) > dateCount(best) ? r : best), null);
        if (busiest) setRouteKey(keyOf(busiest));
      },
      (e: ApiError) => setError(`Could not load routes (${e.status ?? "network"})`),
    );
  }, []);

  const route = routes?.find((r) => keyOf(r) === routeKey) ?? null;
  const reverse = route ? routes?.find((r) => r.origin === route.destination && r.destination === route.origin) ?? null : null;
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

  const departureChoices: Choice[] = departures.map((d) => ({
    value: d,
    text: formatDate(d),
    group: monthFmt.format(new Date(`${d}T00:00:00Z`)),
  }));
  const returnChoices: Choice[] = [
    ...(hasLeg ? [{ value: ONE_WAY, text: "One way", note: "Leg price" }] : []),
    ...returns.map((r) => {
      const n = nightsBetween(departure, r);
      return { value: r, text: formatDate(r), note: `${n} ${n === 1 ? "night" : "nights"}` };
    }),
  ];

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
        </header>
        {routes && routes.length > 0 && (
          <section className="finder" aria-label="Choose a route and dates">
            <div className="finder-route">
              <RouteSearch routes={routes} onPick={(r) => setRouteKey(keyOf(r))} />
              {route && (
                <p className="finder-current">
                  <span>
                    Showing{" "}
                    <b>
                      <End code={route.origin} city={route.origin_city} /> → <End code={route.destination} city={route.destination_city} />
                    </b>
                  </span>
                  {reverse && (
                    <button className="btn-marker" type="button" onClick={() => setRouteKey(keyOf(reverse))}>
                      ⇄ Reverse
                    </button>
                  )}
                </p>
              )}
            </div>
            {departureChoices.length > 0 && (
              <ChoiceChips label="Departs" choices={departureChoices} value={departure} onChange={setDeparture} />
            )}
            {returnChoices.length > 0 && (
              <ChoiceChips label="Returns" choices={returnChoices} value={returnDate} onChange={setReturnDate} />
            )}
          </section>
        )}
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
              baseline={history.baseline}
              label={`Price per adult, ${history.origin} to ${history.destination}, ${dates}: ${points.length} price ${points.length === 1 ? "level" : "levels"}${cheapestNow !== null ? `, now ${formatEur(cheapestNow)}` : ""}${history.baseline ? `, ${history.baseline.tier} Baseline ${formatEur(history.baseline.median_per_adult_eur)}` : ""}.`}
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
          </>
        ) : (
          <p className="meta">Choose a route and departure date.</p>
        )}
      </aside>
    </>
  );
}
