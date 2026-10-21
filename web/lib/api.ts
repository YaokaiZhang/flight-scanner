// Typed client for the HTTP API (through the same-origin /api proxy).

export type PlaceRef = { kind: "airport"; code: string };
export type PlaceSet = { include: PlaceRef[]; exclude: PlaceRef[] };
export type StayNights = { min: number; max: number };
type RoundTripOptions = { stay_nights: StayNights; return_by?: string | null };
export type TripPreset =
  | { preset: "one_way_fixed"; departure: string }
  | { preset: "fixed_dates"; departure: string; return_date: string }
  | ({ preset: "month"; month: string } & RoundTripOptions)
  | ({ preset: "rolling"; within_days: number } & RoundTripOptions)
  | ({ preset: "fixed_departure"; departure: string } & RoundTripOptions)
  | ({ preset: "around_date"; target: string; flex_days: number } & RoundTripOptions);

/** A preset as the API resolved it for today. */
export type TripResolution = {
  kind: "one_way" | "round_trip";
  rolling: boolean;
  departure_start: string;
  departure_end: string;
  stay_nights: StayNights | null;
  return_by: string | null;
  latest_return: string | null;
  trip_count: number;
  expired: boolean;
};
export type PriceThreshold = { amount_eur: number; basis: "total" | "per_adult" };
export type Delivery = "immediate" | "digest";

export type WatchSpec = {
  name: string;
  origins: Omit<PlaceSet, "exclude"> & { exclude?: PlaceRef[] };
  destinations: Omit<PlaceSet, "exclude"> & { exclude?: PlaceRef[] };
  trip_pattern: TripPreset;
  adults: number;
  price_threshold: PriceThreshold | null;
  delivery?: Delivery;
};

export type Watch = WatchSpec & {
  id: number;
  origins: PlaceSet;
  destinations: PlaceSet;
  status: "active" | "paused" | "expired";
  delivery: Delivery;
  created_at: string;
  updated_at: string;
};

export type Deal = {
  id: number;
  watch_id: number;
  watch_name: string;
  origin: string;
  destination: string;
  outbound_date: string;
  return_date: string | null;
  adults: number;
  price_per_adult_eur: number;
  price_total_eur: number;
  source: string;
  observed_at: string;
  ticketing: "one_way" | "single_ticket" | "separate_tickets";
  verification: "verified" | "unverified";
  baseline_tier: string | null;
  detected_at: string;
};

export type TripDates = { departure_date: string; return_date: string };

export type Route = {
  origin: string;
  destination: string;
  departure_dates: string[]; // with Leg-price history
  round_trips: TripDates[]; // with Round-trip-price history
};

export type HistoryPoint = {
  source: string;
  kind: "leg" | "round_trip";
  price_per_adult_eur: number;
  valid_from: string;
  valid_to: string | null;
  last_observed_at: string;
  observations: number;
  airline: string | null;
  stops: number | null;
};

export type RouteHistory = {
  origin: string;
  destination: string;
  departure_date: string;
  return_date: string | null;
  points: HistoryPoint[];
};

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`API ${status}`);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

export const api = {
  listWatches: () => call<Watch[]>("/watches"),
  createWatch: (spec: WatchSpec) =>
    call<Watch>("/watches", { method: "POST", body: JSON.stringify(spec) }),
  resolveTripPattern: (trip_pattern: TripPreset) =>
    call<TripResolution>("/trip-patterns/resolve", { method: "POST", body: JSON.stringify({ trip_pattern }) }),
  listDeals: (watchId?: number) =>
    call<Deal[]>(`/deals${watchId ? `?watch_id=${watchId}` : ""}`),
  listRoutes: () => call<Route[]>("/routes"),
  routeHistory: (origin: string, destination: string, departure: string, returnDate?: string) => {
    const q = new URLSearchParams({ departure_date: departure });
    if (returnDate) q.set("return_date", returnDate);
    return call<RouteHistory>(
      `/routes/${encodeURIComponent(origin)}/${encodeURIComponent(destination)}/history?${q}`,
    );
  },
};
