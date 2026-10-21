"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Watch } from "@/lib/api";
import { formatDate, formatEur } from "@/lib/format";
import { WatchEditor } from "./WatchEditor";

function places(w: Watch, side: "origins" | "destinations") {
  return w[side].include.map((p) => p.code).join(", ");
}

export function WatchesView() {
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.listWatches().then(setWatches, (e: ApiError) => setError(`Could not load Watches (${e.status ?? "network"})`));
  }, []);
  useEffect(load, [load]);

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Watches</h1>
            <p className="lede">
              {watches ? <><b>{watches.filter((w) => w.status === "active").length}</b> active</> : "Loading"}
            </p>
          </div>
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {watches && watches.length === 0 && (
          <div className="empty"><strong>No Watches yet</strong>Create one in the editor.</div>
        )}
        {watches && watches.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Watch</th><th>From</th><th>To</th><th>Departure</th>
                  <th className="num">Adults</th><th className="num">Threshold</th><th>Alerts by</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {watches.map((w) => (
                  <tr key={w.id} className={w.status === "paused" ? "paused" : undefined}>
                    <td className="row-title">{w.name}</td>
                    <td data-label="From">{places(w, "origins")}</td>
                    <td data-label="To">{places(w, "destinations")}</td>
                    <td data-label="Departure">{formatDate(w.trip_pattern.departure)} · one way</td>
                    <td data-label="Adults" className="num">{w.adults}</td>
                    <td data-label="Threshold" className="num">
                      {w.price_threshold
                        ? `${formatEur(w.price_threshold.amount_eur)}${w.price_threshold.basis === "per_adult" ? " /adult" : ""}`
                        : "none"}
                    </td>
                    <td data-label="Alerts by">
                      {w.channels.map((c) => (c === "email" ? "Email" : "Telegram")).join(" + ")}
                    </td>
                    <td data-label="Status">
                      <span className={`tag ${w.status === "active" ? "verified" : "off"}`}>{w.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
      <aside className="inspector" aria-label="Watch editor">
        <WatchEditor onCreated={load} />
      </aside>
    </>
  );
}
