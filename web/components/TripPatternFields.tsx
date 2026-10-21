"use client";

// Trip-pattern section of the Watch editor. Only the walking-skeleton preset (one way, fixed date)
// exists so far; ticket 04 replaces this component with the full preset picker and the resolved
// window drawing, keeping the same props.

import type { TripPreset } from "@/lib/api";

export function TripPatternFields({
  value,
  onChange,
}: {
  value: TripPreset | null;
  onChange: (next: TripPreset) => void;
}) {
  return (
    <label className="field">
      <span>Departure (one way)</span>
      <input
        className="input"
        name="departure"
        type="date"
        required
        value={value?.departure ?? ""}
        onChange={(e) => onChange({ preset: "one_way_fixed", departure: e.target.value })}
      />
    </label>
  );
}
