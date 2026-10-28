"use client";

import { useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  placeKey,
  type Channel,
  type Delivery,
  type Place,
  type PlaceSet,
  type ThresholdMatch,
  type Watch,
  type WatchSpec,
} from "@/lib/api";
import type { WatchDraft } from "@/lib/watchDraft";
import { Icon, PlacePicker } from "./PlacePicker";
import { EMPTY_TRIP_DRAFT, TripPatternFields, toPreset, tripDraftOf, type TripDraft } from "./TripPatternFields";

type Draft = {
  name: string;
  origins: PlaceSet;
  destinations: PlaceSet;
  adults: number;
  threshold: string;
  basis: "total" | "per_adult";
  match: ThresholdMatch;
  sensitivity_pct: number;
  channels: Channel[];
  delivery: Delivery;
};

const EMPTY: Draft = {
  name: "",
  origins: { include: [], exclude: [] },
  destinations: { include: [], exclude: [] },
  adults: 1,
  threshold: "",
  basis: "total",
  match: "both",
  sensitivity_pct: 30,
  channels: ["email", "telegram"],
  delivery: "immediate",
};

function draftOf(w: WatchSpec): Draft {
  return {
    name: w.name,
    origins: { include: w.origins.include, exclude: w.origins.exclude ?? [] },
    destinations: { include: w.destinations.include, exclude: w.destinations.exclude ?? [] },
    adults: w.adults,
    threshold: w.price_threshold ? String(w.price_threshold.amount_eur) : "",
    basis: w.price_threshold?.basis ?? "total",
    match: w.price_threshold?.match ?? "both",
    sensitivity_pct: w.sensitivity_pct ?? EMPTY.sensitivity_pct,
    channels: w.channels.length ? w.channels : EMPTY.channels,
    delivery: w.delivery ?? EMPTY.delivery,
  };
}

export function problem(err: unknown): string {
  if (!(err instanceof ApiError)) return "Could not save (network).";
  if (err.status !== 422) return `Could not save (${err.status}).`;
  const detail = (err.detail as { detail?: { msg?: string }[] } | null)?.detail;
  const msgs = Array.isArray(detail) ? detail.map((d) => d.msg).filter(Boolean) : [];
  return msgs.length ? `Check the fields: ${msgs.join("; ")}.` : "Check the fields: some values are not valid.";
}

/** Create a Watch (no `watch`) or edit one: Places, trip, adults, threshold, sensitivity, delivery.
 *  A `draft` (e.g. a Watch assistant proposal) prefills the create form. */
export function WatchEditor({
  watch,
  draft: proposed,
  onSaved,
  onDeleted,
  onClose,
}: {
  watch: Watch | null;
  draft?: WatchDraft | null;
  onSaved: (w: Watch) => void;
  onDeleted: (id: number) => void;
  onClose: () => void;
}) {
  const start = watch ?? proposed?.spec ?? null;
  const [draft, setDraft] = useState<Draft>(start ? draftOf(start) : EMPTY);
  const [names, setNames] = useState(
    () => new Map((watch?.places ?? proposed?.places ?? []).map((p) => [placeKey(p), p])),
  );
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [trip, setTrip] = useState<TripDraft>(start ? tripDraftOf(start.trip_pattern) : EMPTY_TRIP_DRAFT);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const toggleChannel = (c: Channel, on: boolean) =>
    set("channels", on ? [...new Set([...draft.channels, c])].sort() : draft.channels.filter((x) => x !== c));
  const remember = (p?: Place) => p && setNames((m) => new Map(m).set(placeKey(p), p));

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } catch (err) {
      setMessage({ ok: false, text: problem(err) });
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!draft.origins.include.length || !draft.destinations.include.length) {
      setMessage({ ok: false, text: "Add at least one origin and one destination Place." });
      return;
    }
    const tripPattern = toPreset(trip);
    if (!tripPattern) {
      setMessage({ ok: false, text: "Complete the Trip pattern." });
      return;
    }
    if (draft.channels.length === 0) {
      setMessage({ ok: false, text: "Choose at least one Alert channel." });
      return;
    }
    const threshold = draft.threshold.trim();
    const spec: WatchSpec = {
      name: draft.name.trim(),
      origins: draft.origins,
      destinations: draft.destinations,
      trip_pattern: tripPattern,
      adults: draft.adults,
      price_threshold: threshold ? { amount_eur: Number(threshold), basis: draft.basis, match: draft.match } : null,
      sensitivity_pct: draft.sensitivity_pct,
      channels: draft.channels,
      delivery: draft.delivery,
    };
    run(async () => {
      const saved = watch ? await api.updateWatch(watch.id, spec) : await api.createWatch(spec);
      setMessage({ ok: true, text: `Saved “${saved.name}”.` });
      if (!watch) {
        setDraft(EMPTY);
        setTrip(EMPTY_TRIP_DRAFT);
      }
      onSaved(saved);
    });
  }

  const togglePause = () =>
    watch &&
    run(async () => {
      const w = watch.status === "active" ? await api.pauseWatch(watch.id) : await api.resumeWatch(watch.id);
      setMessage({ ok: true, text: w.status === "paused" ? "Paused." : "Resumed." });
      onSaved(w);
    });

  const remove = () =>
    watch &&
    run(async () => {
      await api.deleteWatch(watch.id);
      onDeleted(watch.id);
    });

  return (
    <section aria-labelledby="editor-title">
      <h2 className="widget-label" id="editor-title">{watch ? "Edit Watch" : "New Watch"}</h2>
      {!watch && proposed && <p className="meta draft-note">Drafted by the Watch assistant. Check it, then create.</p>}
      <form className="editor" onSubmit={submit}>
        <label className="field">
          <span>Name</span>
          <input
            className="input"
            name="name"
            required
            maxLength={120}
            placeholder="Barcelona weekend"
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </label>
        <PlacePicker
          label="From"
          value={draft.origins}
          names={names}
          onChange={(v, p) => {
            remember(p);
            set("origins", v);
          }}
        />
        <PlacePicker
          label="To"
          value={draft.destinations}
          names={names}
          onChange={(v, p) => {
            remember(p);
            set("destinations", v);
          }}
        />
        <TripPatternFields draft={trip} onChange={setTrip} />
        <div className="row2">
          <div className="field">
            <span className="field-label" id="adults-label">Adults</span>
            <div className="stepper" role="group" aria-labelledby="adults-label">
              <button type="button" aria-label="Fewer adults" disabled={draft.adults <= 1} onClick={() => set("adults", draft.adults - 1)}>
                <Icon name="minus" />
              </button>
              <span className="stepper-value">{draft.adults}</span>
              <button type="button" aria-label="More adults" disabled={draft.adults >= 9} onClick={() => set("adults", draft.adults + 1)}>
                <Icon name="plus" />
              </button>
            </div>
          </div>
          <label className="field">
            <span>Price threshold (EUR)</span>
            <input
              className="input"
              name="threshold"
              type="number"
              min={1}
              step="any"
              placeholder="optional"
              value={draft.threshold}
              onChange={(e) => set("threshold", e.target.value)}
            />
          </label>
        </div>
        <fieldset className="field" style={{ border: 0 }}>
          <legend className="field-label">Threshold applies to</legend>
          <div className="choice">
            <label>
              <input type="radio" name="basis" value="total" checked={draft.basis === "total"} onChange={() => set("basis", "total")} /> Total
            </label>
            <label>
              <input type="radio" name="basis" value="per_adult" checked={draft.basis === "per_adult"} onChange={() => set("basis", "per_adult")} /> Per adult
            </label>
          </div>
        </fieldset>
        {draft.threshold.trim() && (
          <div className="join">
            <div className="seg" role="group" aria-label="Threshold and Baseline">
              {(["both", "either"] as const).map((m) => (
                <button key={m} type="button" aria-pressed={draft.match === m} onClick={() => set("match", m)}>
                  {m === "both" ? "and" : "or"}
                </button>
              ))}
            </div>
          </div>
        )}
        <label className="field">
          <span>Sensitivity · {draft.sensitivity_pct}% below Baseline</span>
          <input
            type="range"
            name="sensitivity"
            min={10}
            max={60}
            step={5}
            value={draft.sensitivity_pct}
            onChange={(e) => set("sensitivity_pct", Number(e.target.value))}
          />
        </label>
        <fieldset className="field" style={{ border: 0 }}>
          <legend className="field-label">Send Alerts by</legend>
          <div className="choice">
            {(["email", "telegram"] as const).map((c) => (
              <label key={c}>
                <input
                  type="checkbox"
                  name="channels"
                  value={c}
                  checked={draft.channels.includes(c)}
                  onChange={(e) => toggleChannel(c, e.target.checked)}
                />{" "}
                {c === "email" ? "Email" : "Telegram"}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="field" style={{ border: 0 }}>
          <legend className="field-label">Delivery</legend>
          <div className="choice">
            <label>
              <input type="radio" name="delivery" value="immediate" checked={draft.delivery === "immediate"} onChange={() => set("delivery", "immediate")} /> Immediate
            </label>
            <label>
              <input type="radio" name="delivery" value="digest" checked={draft.delivery === "digest"} onChange={() => set("delivery", "digest")} /> Daily Digest
            </label>
          </div>
        </fieldset>
        <div className="actions">
          <button className="btn-marker primary" type="submit" disabled={busy}>
            {busy ? "Saving" : watch ? "Save Watch" : "Create Watch"}
          </button>
          {watch && (
            <button className="btn-marker" type="button" disabled={busy} onClick={togglePause}>
              {watch.status === "active" ? "Pause" : "Resume"}
            </button>
          )}
          {watch && (
            <button className="btn-marker" type="button" onClick={onClose}>
              New
            </button>
          )}
          <span className="spacer" />
          {watch &&
            (confirmDelete ? (
              <button className="btn-marker danger" type="button" disabled={busy} onClick={remove}>
                Confirm delete
              </button>
            ) : (
              <button className="btn-marker danger" type="button" onClick={() => setConfirmDelete(true)}>
                Delete
              </button>
            ))}
        </div>
        <p className={message?.ok === false ? "error" : "saved"} role="status">{message?.text}</p>
      </form>
    </section>
  );
}
