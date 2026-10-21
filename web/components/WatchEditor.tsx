"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError, type WatchSpec } from "@/lib/api";
import { EMPTY_TRIP_DRAFT, TripPatternFields, toPreset, type TripDraft } from "./TripPatternFields";

const iata = (s: string) => s.trim().toUpperCase();

export function WatchEditor({ onCreated }: { onCreated: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [trip, setTrip] = useState<TripDraft>(EMPTY_TRIP_DRAFT);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const threshold = String(f.get("threshold") ?? "").trim();
    const tripPattern = toPreset(trip);
    if (!tripPattern) {
      setMessage({ ok: false, text: "Complete the Trip pattern." });
      return;
    }
    const spec: WatchSpec = {
      name: String(f.get("name") ?? "").trim(),
      origins: { include: [{ kind: "airport", code: iata(String(f.get("origin"))) }] },
      destinations: { include: [{ kind: "airport", code: iata(String(f.get("destination"))) }] },
      trip_pattern: tripPattern,
      adults: Number(f.get("adults")),
      price_threshold: threshold
        ? { amount_eur: Number(threshold), basis: f.get("basis") === "per_adult" ? "per_adult" : "total" }
        : null,
    };
    setBusy(true);
    setMessage(null);
    try {
      const w = await api.createWatch(spec);
      setMessage({ ok: true, text: `Saved “${w.name}”.` });
      form.reset();
      setTrip(EMPTY_TRIP_DRAFT);
      onCreated();
    } catch (err) {
      const status = err instanceof ApiError ? err.status : "network";
      setMessage({ ok: false, text: status === 422 ? "Check the fields: some values are not valid." : `Could not save (${status}).` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="editor-title">
      <h2 className="widget-label" id="editor-title">New Watch</h2>
      <form className="editor" onSubmit={submit}>
        <label className="field">
          <span>Name</span>
          <input className="input" name="name" required maxLength={120} placeholder="Barcelona weekend" />
        </label>
        <div className="row2">
          <label className="field">
            <span>From (airport)</span>
            <input className="input" name="origin" required pattern="[A-Za-z]{3}" maxLength={3} placeholder="HEL" />
          </label>
          <label className="field">
            <span>To (airport)</span>
            <input className="input" name="destination" required pattern="[A-Za-z]{3}" maxLength={3} placeholder="BCN" />
          </label>
        </div>
        <TripPatternFields draft={trip} onChange={setTrip} />
        <label className="field">
          <span>Adults</span>
          <input className="input" name="adults" type="number" min={1} max={9} defaultValue={1} required />
        </label>
        <label className="field">
          <span>Price threshold (EUR)</span>
          <input className="input" name="threshold" type="number" min={1} step="any" placeholder="optional" />
        </label>
        <fieldset className="field" style={{ border: 0 }}>
          <legend className="field-label">Threshold applies to</legend>
          <div className="choice">
            <label><input type="radio" name="basis" value="total" defaultChecked /> Total</label>
            <label><input type="radio" name="basis" value="per_adult" /> Per adult</label>
          </div>
        </fieldset>
        <div>
          <button className="btn-marker primary" type="submit" disabled={busy}>
            {busy ? "Saving" : "Create Watch"}
          </button>
        </div>
        <p className={message?.ok === false ? "error" : "saved"} role="status">{message?.text}</p>
      </form>
    </section>
  );
}
