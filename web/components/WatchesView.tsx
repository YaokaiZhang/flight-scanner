"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, placeKey, type PlaceRef, type Watch } from "@/lib/api";
import { formatEur } from "@/lib/format";
import { describePreset } from "./TripPatternFields";
import { WatchEditor } from "./WatchEditor";

function places(w: Watch, side: "origins" | "destinations") {
  const names = new Map(w.places.map((p) => [placeKey(p), p.kind === "airport" ? p.code : p.name]));
  const name = (r: PlaceRef) => names.get(placeKey(r)) ?? r.code;
  const inc = w[side].include.map(name).join(", ");
  const exc = w[side].exclude.map(name);
  return exc.length ? `${inc} − ${exc.join(", ")}` : inc;
}

const airports = (n: number) => `${n.toLocaleString("en-GB")} ${n === 1 ? "airport" : "airports"}`;

export function WatchesView() {
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(() => {
    api.listWatches().then(setWatches, (e: ApiError) => setError(`Could not load Watches (${e.status ?? "network"})`));
  }, []);
  useEffect(load, [load]);

  const current = watches?.find((w) => w.id === selected) ?? null;

  // Bring the editor into view (it sits below the table on narrow screens) when a Watch is picked.
  useEffect(() => {
    if (selected !== null) document.getElementById("editor-title")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

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
          {current && (
            <button className="btn-marker primary" type="button" onClick={() => setSelected(null)}>
              New Watch
            </button>
          )}
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
                  <th>Watch</th><th>Where</th><th>Trip pattern</th>
                  <th className="num">Adults</th><th className="num">Threshold</th><th>Alerts by</th><th>Status</th>
                  <th><span className="sr-only">Edit</span></th>
                </tr>
              </thead>
              <tbody>
                {watches.map((w) => (
                  <tr
                    key={w.id}
                    className={`selectable${w.status !== "active" ? " paused" : ""}`}
                    aria-selected={w.id === selected}
                    onClick={() => setSelected(w.id)}
                  >
                    <td className="row-title">
                      <button type="button" onClick={() => setSelected(w.id)}>{w.name}</button>
                      <div className="sub">sensitivity {w.sensitivity_pct}%</div>
                    </td>
                    <td data-label="Where">
                      {places(w, "origins")} → {places(w, "destinations")}
                      <div className="sub">
                        {airports(w.resolved.origins)} → {airports(w.resolved.destinations)}
                      </div>
                    </td>
                    <td data-label="Trip pattern">{describePreset(w.trip_pattern)}</td>
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
                    <td className="row-edit">
                      <button
                        className="btn-marker"
                        type="button"
                        aria-label={`Edit ${w.name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelected(w.id);
                        }}
                      >
                        {w.id === selected ? "Editing" : "Edit"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
      <aside className="inspector" aria-label="Watch editor">
        <WatchEditor
          key={current ? current.id : "new"}
          watch={current}
          onSaved={load}
          onDeleted={() => {
            setSelected(null);
            load();
          }}
          onClose={() => setSelected(null)}
        />
      </aside>
    </>
  );
}
