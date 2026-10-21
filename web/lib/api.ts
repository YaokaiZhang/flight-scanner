// Typed client for the HTTP API (through the same-origin /api proxy).

export type PlaceKind = "airport" | "city" | "country" | "region";
export type PlaceRef = { kind: PlaceKind; code: string };
export type PlaceSet = { include: PlaceRef[]; exclude: PlaceRef[] };
/** A Place as the API describes it (search results, Watch places). */
export type Place = PlaceRef & { name: string; context: string | null; airport_count: number };
/** Region tree node; `children` is null when not expanded (or for airports). */
export type TreeNode = Place & { via: string | null; children: TreeNode[] | null };
export type Resolution = { airport_count: number; airports: string[]; reference_version: string };
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
  sensitivity_pct?: number;
};

export type Watch = WatchSpec & {
  id: number;
  origins: PlaceSet;
  destinations: PlaceSet;
  sensitivity_pct: number;
  status: "active" | "paused";
  delivery: Delivery;
  created_at: string;
  updated_at: string;
  places: Place[];
  resolved: { origins: number; destinations: number };
};

export const placeKey = (p: PlaceRef) => `${p.kind}:${p.code}`;

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
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  listWatches: () => call<Watch[]>("/watches"),
  createWatch: (spec: WatchSpec) => call<Watch>("/watches", json("POST", spec)),
  updateWatch: (id: number, spec: WatchSpec) => call<Watch>(`/watches/${id}`, json("PUT", spec)),
  pauseWatch: (id: number) => call<Watch>(`/watches/${id}/pause`, json("POST")),
  resumeWatch: (id: number) => call<Watch>(`/watches/${id}/resume`, json("POST")),
  deleteWatch: (id: number) => call<null>(`/watches/${id}`, json("DELETE")),
  searchPlaces: (q: string, limit = 8) =>
    call<Place[]>(`/places/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  resolvePlaces: (places: PlaceSet) => call<Resolution>("/places/resolve", json("POST", places)),
  placeTree: (p: PlaceRef, depth = 1) =>
    call<TreeNode>(`/places/${p.kind}/${encodeURIComponent(p.code)}/tree?depth=${depth}`),
  listDeals: (filter: { watchId?: number; status?: DealStatus } = {}) => {
    const q = new URLSearchParams();
    if (filter.watchId) q.set("watch_id", String(filter.watchId));
    if (filter.status) q.set("status", filter.status);
    return call<Deal[]>(`/deals${q.size ? `?${q}` : ""}`);
  },
  rateDeal: (id: number, rating: Rating | null) =>
    call<Deal>(`/deals/${id}/feedback`, json("POST", { rating })),
  listRoutes: () => call<Route[]>("/routes"),
  routeHistory: (origin: string, destination: string, departure: string, returnDate?: string) => {
    const q = new URLSearchParams({ departure_date: departure });
    if (returnDate) q.set("return_date", returnDate);
    return call<RouteHistory>(
      `/routes/${encodeURIComponent(origin)}/${encodeURIComponent(destination)}/history?${q}`,
    );
  },
};
