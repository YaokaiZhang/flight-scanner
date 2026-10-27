"use client";

// The Trip-pattern section of the Watch editor: preset picker, its fields, and the resolved
// departure window and Stay-night range as the API understood it (the dimension line).

import { useEffect, useState } from "react";
import { api, ApiError, type TripPreset, type TripResolution } from "@/lib/api";
import { formatDate } from "@/lib/format";

type PresetName = TripPreset["preset"];

const PRESETS: { value: PresetName; label: string; hint: string }[] = [
  { value: "fixed_dates", label: "Exact dates", hint: "Out and back on the dates you pick." },
  { value: "one_way_fixed", label: "One way", hint: "A single flight on the date you pick." },
  {
    value: "fixed_departure",
    label: "Exact departure, flexible return",
    hint: "Leave on one date and come back after any stay length in your range.",
  },
  {
    value: "around_date",
    label: "Around a date",
    hint: "Leave within a few days either side of a date, for any stay length in your range.",
  },
  { value: "month", label: "Sometime in a month", hint: "Leave on any day of the month, for any stay length in your range." },
  {
    value: "rolling",
    label: "Anytime soon",
    hint: "Leave any day from today up to a number of days ahead; the window moves forward each day.",
  },
];

/** Every input the section can show, as typed; a preset is built from the ones it needs. */
export type TripDraft = {
  preset: PresetName;
  departure: string;
  return_date: string;
  month: string;
  within_days: string;
  target: string;
  flex_days: string;
  min_nights: string;
  max_nights: string;
  return_by: string;
};

export const EMPTY_TRIP_DRAFT: TripDraft = {
  preset: "one_way_fixed",
  departure: "",
  return_date: "",
  month: "",
  within_days: "60",
  target: "",
  flex_days: "2",
  min_nights: "3",
  max_nights: "6",
  return_by: "",
};

const int = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s) : null);

/** The preset the draft describes, or null while a required field is missing. */
export function toPreset(d: TripDraft): TripPreset | null {
  if (d.preset === "one_way_fixed") return d.departure ? { preset: d.preset, departure: d.departure } : null;
  if (d.preset === "fixed_dates") {
    return d.departure && d.return_date
      ? { preset: d.preset, departure: d.departure, return_date: d.return_date }
      : null;
  }
  const min = int(d.min_nights);
  const max = int(d.max_nights);
  if (min === null || max === null) return null;
  const common = { stay_nights: { min, max }, return_by: d.return_by || null };
  switch (d.preset) {
    case "month":
      return d.month ? { preset: d.preset, month: d.month, ...common } : null;
    case "rolling": {
      const n = int(d.within_days);
      return n === null ? null : { preset: d.preset, within_days: n, ...common };
    }
    case "fixed_departure":
      return d.departure ? { preset: d.preset, departure: d.departure, ...common } : null;
    case "around_date": {
      const k = int(d.flex_days);
      return d.target && k !== null ? { preset: d.preset, target: d.target, flex_days: k, ...common } : null;
    }
  }
  return null;
}

/** The draft for a stored preset (editing an existing Watch). */
export function tripDraftOf(p: TripPreset): TripDraft {
  const d: TripDraft = { ...EMPTY_TRIP_DRAFT, preset: p.preset };
  if ("departure" in p) d.departure = p.departure;
  if ("return_date" in p) d.return_date = p.return_date;
  if ("month" in p) d.month = p.month;
  if ("within_days" in p) d.within_days = String(p.within_days);
  if ("target" in p) d.target = p.target;
  if ("flex_days" in p) d.flex_days = String(p.flex_days);
  if ("stay_nights" in p) {
    d.min_nights = String(p.stay_nights.min);
    d.max_nights = String(p.stay_nights.max);
    d.return_by = p.return_by ?? "";
  }
  return d;
}

/** A short description of a stored preset, for the Watches table. */
export function describePreset(p: TripPreset): string {
  const n = "stay_nights" in p ? `${p.stay_nights.min}–${p.stay_nights.max} nights` : "";
  const by = "return_by" in p && p.return_by ? ` · back by ${formatDate(p.return_by)}` : "";
  switch (p.preset) {
    case "one_way_fixed":
      return `One way on ${formatDate(p.departure)}`;
    case "fixed_dates":
      return `${formatDate(p.departure)} → ${formatDate(p.return_date)}`;
    case "month": {
      const m = new Date(`${p.month}-01T00:00:00Z`).toLocaleString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
      return `${n}, leaving sometime in ${m}${by}`;
    }
    case "rolling":
      return `${n}, leaving within the next ${p.within_days} days${by}`;
    case "fixed_departure":
      return `Leave ${formatDate(p.departure)}, stay ${n}${by}`;
    case "around_date":
      return `${n}, leaving ${formatDate(p.target)} give or take ${p.flex_days} ${p.flex_days === 1 ? "day" : "days"}${by}`;
  }
  return "";
}

const DAY = 86_400_000;
const days = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / DAY);

function DimensionLine({ r }: { r: TripResolution }) {
  const width = days(r.departure_start, r.departure_end) + 1;
  const tail = r.latest_return ? Math.max(0, days(r.departure_end, r.latest_return)) : 0;
  const span = width + tail;
  const pct = (v: number) => `${((v / span) * 100).toFixed(2)}%`;
  const label = `${width} ${width === 1 ? "day" : "days"} · depart`;
  const aria =
    `Departure window ${formatDate(r.departure_start)} to ${formatDate(r.departure_end)}` +
    (r.latest_return ? `; returns as late as ${formatDate(r.latest_return)}` : "");
  return (
    <div className={`dimension${tail > 0 ? " has-ret" : ""}`} role="img" aria-label={aria}>
      <div className="line" style={{ left: 0, width: pct(width) }} />
      <span className="lbl top" style={{ left: pct(width / 2) }}>{label}</span>
      <div className="axis" />
      <div className="win" style={{ left: 0, width: pct(width) }} />
      {tail > 0 && <div className="ret" style={{ left: pct(width), width: pct(tail) }} />}
      <span className="lbl bot" style={{ left: 0 }}>{formatDate(r.departure_start)}</span>
      {width > 1 && (
        <span className="lbl bot" style={{ left: pct(width), transform: "translateX(-100%)" }}>
          {formatDate(r.departure_end)}
        </span>
      )}
      {tail > 0 && r.latest_return && (
        <span className="lbl bot ret-lbl" style={{ left: "100%", transform: "translateX(-100%)" }}>
          ↳ {formatDate(r.latest_return)}
        </span>
      )}
    </div>
  );
}

function Resolved({ preset }: { preset: TripPreset | null }) {
  const [state, setState] = useState<{ r: TripResolution | null; error: string | null }>({ r: null, error: null });
  const key = preset ? JSON.stringify(preset) : null;

  useEffect(() => {
    if (!key) return;
    let live = true;
    const t = setTimeout(() => {
      api.resolveTripPattern(JSON.parse(key) as TripPreset).then(
        (r) => live && setState({ r, error: null }),
        (e: ApiError) =>
          live && setState({ r: null, error: e.status === 422 ? "These dates don’t make a valid Trip pattern." : "Could not resolve the Trip pattern." }),
      );
    }, 200);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [key]);

  if (!key) return <p className="trip-summary">Fill in the dates to see the departure window.</p>;
  const { r, error } = state;
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!r) return <p className="trip-summary">Resolving…</p>;
  const nights = r.stay_nights
    ? r.stay_nights.min === r.stay_nights.max
      ? `${r.stay_nights.min} nights`
      : `${r.stay_nights.min}–${r.stay_nights.max} nights`
    : "one way";
  return (
    <div className="trip-resolved" data-testid="trip-resolution">
      <DimensionLine r={r} />
      <p className="trip-summary">
        Departs <b>{formatDate(r.departure_start)}</b>
        {r.departure_end !== r.departure_start && <> – <b>{formatDate(r.departure_end)}</b></>}
        {r.rolling && " (moves forward daily)"} · <b>{nights}</b>
        {r.latest_return && <> · back by <b>{formatDate(r.latest_return)}</b></>}
        {" · "}
        {r.trip_count} {r.trip_count === 1 ? "trip" : "trips"}
      </p>
      {r.expired && <p className="error">This departure window has passed; the Watch would be expired.</p>}
      {!r.expired && r.trip_count === 0 && <p className="error">No trips fit: check the latest return date.</p>}
    </div>
  );
}

export function TripPatternFields({ draft, onChange }: { draft: TripDraft; onChange: (d: TripDraft) => void }) {
  const set = (k: keyof TripDraft) => (e: { target: { value: string } }) => onChange({ ...draft, [k]: e.target.value });
  const p = draft.preset;
  const roundTripRange = p !== "one_way_fixed" && p !== "fixed_dates";

  return (
    <div className="trip-pattern">
      <label className="field">
        <span>Trip pattern</span>
        <select className="input" value={p} onChange={set("preset")}>
          {PRESETS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </label>
      <p className="trip-summary">{PRESETS.find((o) => o.value === p)?.hint}</p>

      {p === "one_way_fixed" && (
        <label className="field">
          <span>Departure date</span>
          <input className="input" type="date" required value={draft.departure} onChange={set("departure")} />
        </label>
      )}
      {p === "fixed_dates" && (
        <div className="row2">
          <label className="field"><span>Departure date</span>
            <input className="input" type="date" required value={draft.departure} onChange={set("departure")} /></label>
          <label className="field"><span>Return date</span>
            <input className="input" type="date" required min={draft.departure || undefined} value={draft.return_date} onChange={set("return_date")} /></label>
        </div>
      )}
      {p === "month" && (
        <label className="field"><span>Departure month</span>
          <input className="input" type="month" required placeholder="2026-11" value={draft.month} onChange={set("month")} /></label>
      )}
      {p === "rolling" && (
        <label className="field"><span>Leave within the next … days</span>
          <input className="input" type="number" min={0} max={365} required value={draft.within_days} onChange={set("within_days")} /></label>
      )}
      {p === "fixed_departure" && (
        <label className="field"><span>Departure date</span>
          <input className="input" type="date" required value={draft.departure} onChange={set("departure")} /></label>
      )}
      {p === "around_date" && (
        <div className="row2">
          <label className="field"><span>Around this date</span>
            <input className="input" type="date" required value={draft.target} onChange={set("target")} /></label>
          <label className="field"><span>Give or take (days)</span>
            <input className="input" type="number" min={0} max={30} required value={draft.flex_days} onChange={set("flex_days")} /></label>
        </div>
      )}
      {roundTripRange && (
        <>
          <div className="row2">
            <label className="field"><span>Shortest stay (nights)</span>
              <input className="input" type="number" min={0} max={60} required value={draft.min_nights} onChange={set("min_nights")} /></label>
            <label className="field"><span>Longest stay (nights)</span>
              <input className="input" type="number" min={Number(draft.min_nights) || 0} max={60} required value={draft.max_nights} onChange={set("max_nights")} /></label>
          </div>
          <label className="field"><span>Be back by (optional)</span>
            <input className="input" type="date" value={draft.return_by} onChange={set("return_by")} /></label>
        </>
      )}

      <Resolved preset={toPreset(draft)} />
    </div>
  );
}
