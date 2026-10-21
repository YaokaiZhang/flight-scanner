// Typed client for the HTTP API (through the same-origin /api proxy).

export type PlaceRef = { kind: "airport"; code: string };
export type PlaceSet = { include: PlaceRef[]; exclude: PlaceRef[] };
export type TripPreset = { preset: "one_way_fixed"; departure: string };
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
  listDeals: (watchId?: number) =>
    call<Deal[]>(`/deals${watchId ? `?watch_id=${watchId}` : ""}`),
};
