// Typed client for the HTTP API (through the same-origin /api proxy).

export type PlaceRef = { kind: "airport"; code: string };
export type PlaceSet = { include: PlaceRef[]; exclude: PlaceRef[] };
export type TripPreset = { preset: "one_way_fixed"; departure: string };
export type PriceThreshold = { amount_eur: number; basis: "total" | "per_adult" };
export type Delivery = "immediate" | "digest";
export type Channel = "email" | "telegram";

export type WatchSpec = {
  name: string;
  origins: Omit<PlaceSet, "exclude"> & { exclude?: PlaceRef[] };
  destinations: Omit<PlaceSet, "exclude"> & { exclude?: PlaceRef[] };
  trip_pattern: TripPreset;
  adults: number;
  price_threshold: PriceThreshold | null;
  delivery?: Delivery;
  channels: Channel[];
};

export type Watch = WatchSpec & {
  id: number;
  origins: PlaceSet;
  destinations: PlaceSet;
  status: "active" | "paused";
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
  verification: "verified" | "unverified";
  baseline_tier: string | null;
  detected_at: string;
  airlines: string | null;
  stops: number | null;
  travel_minutes: number | null;
  separate_tickets: boolean;
  booking_url: string;
  baseline_per_adult_eur: number | null;
  pct_below_baseline: number | null;
  feedback: { rating: Rating; via: "telegram" | "web" } | null;
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

export type Rating = "up" | "down";
export type DealStatus = "verified" | "unverified";

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
  listDeals: (filter: { watchId?: number; status?: DealStatus } = {}) => {
    const q = new URLSearchParams();
    if (filter.watchId) q.set("watch_id", String(filter.watchId));
    if (filter.status) q.set("status", filter.status);
    return call<Deal[]>(`/deals${q.size ? `?${q}` : ""}`);
  },
  rateDeal: (id: number, rating: Rating | null) =>
    call<Deal>(`/deals/${id}/feedback`, { method: "POST", body: JSON.stringify({ rating }) }),
  listRoutes: () => call<Route[]>("/routes"),
  routeHistory: (origin: string, destination: string, departure: string, returnDate?: string) => {
    const q = new URLSearchParams({ departure_date: departure });
    if (returnDate) q.set("return_date", returnDate);
    return call<RouteHistory>(
      `/routes/${encodeURIComponent(origin)}/${encodeURIComponent(destination)}/history?${q}`,
    );
  },
};
