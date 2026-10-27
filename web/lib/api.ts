// Typed client for the HTTP API (through the same-origin /api proxy).

export type PlaceKind = "airport" | "city" | "country" | "region";
export type PlaceRef = { kind: PlaceKind; code: string };
export type PlaceSet = { include: PlaceRef[]; exclude: PlaceRef[] };
/** A Place as the API describes it (search results, Watch places). */
export type Place = PlaceRef & { name: string; context: string | null; airport_count: number };
/** Region tree node; `children` is null when not expanded (or for airports). */
export type TreeNode = Place & { via: string | null; children: TreeNode[] | null };
export type Resolution = { airport_count: number; airports: string[]; reference_version: string };
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
  status: "active" | "paused" | "expired";
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
  ticketing: "one_way" | "single_ticket" | "separate_tickets";
  // failed = checked live and no longer a Deal: recorded, never alerted
  verification: "verified" | "unverified" | "failed";
  // live_deal | live_not_a_deal | not_found | budget_exhausted | no_verifier | verifier_error
  verification_reason: string | null;
  verified_at: string | null; // when it was checked live
  verified_price_total_eur: number | null; // the live price for the Watch's adults
  verified_price_per_adult_eur: number | null;
  baseline_tier: string | null;
  detected_at: string;
  airlines: string | null;
  stops: number | null;
  travel_minutes: number | null;
  separate_tickets: boolean;
  booking_url: string;
  baseline_per_adult_eur: number | null;
  pct_below_baseline: number | null;
  baseline: DealBaseline | null; // the Baseline version the Deal was judged against
  deal_context: string | null; // why it might be cheap (web research), when found in time
  feedback: { rating: Rating; via: "telegram" | "web" } | null;
};

export type BaselineTier = "route" | "country" | "price_insight" | "provisional";

export type DealBaseline = {
  tier: BaselineTier;
  per_adult_eur: number;
  method: string | null;
  computed_at: string | null;
  observations: number | null;
  observation_days: number | null;
};

// The current Baseline of a trip's key: median ± MAD.
export type BaselineBand = {
  tier: BaselineTier;
  median_per_adult_eur: number;
  low_per_adult_eur: number;
  high_per_adult_eur: number;
  method: string;
  computed_at: string;
  observations: number;
  observation_days: number;
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
  baseline: BaselineBand | null;
};

export type Rating = "up" | "down";

// Backtest (ticket 11): each past Deal judged from the prices seen after it.
export type Outcome = "real_dip" | "stayed_low" | "pending" | "inconclusive" | "unjudged";

export type PastDeal = {
  deal_id: number;
  origin: string;
  destination: string;
  outbound_date: string;
  return_date: string | null;
  detected_at: string;
  baseline_tier: string | null;
  price_per_adult_eur: number; // at its first Alert
  baseline_per_adult_eur: number | null;
  pct_below_baseline: number | null;
  later_observation_days: number;
  highest_later_price_per_adult_eur: number | null;
  outcome: Outcome;
  rating: Rating | null;
};

export type FeedbackCounts = { up: number; down: number; unrated: number };

export type WatchBacktest = {
  watch_id: number;
  watch_name: string;
  status: string;
  sensitivity_pct: number;
  deals: number;
  outcomes: Record<Outcome, number>;
  precision: number | null; // real dips / (real dips + stayed low)
  alerts: number;
  weeks: number;
  alerts_per_week: number;
  pct_below_baseline: {
    median: number | null;
    buckets: { from_pct: number; to_pct: number | null; deals: number }[];
  };
  feedback: FeedbackCounts & { by_outcome: (FeedbackCounts & { outcome: Outcome })[] };
  past_deals: PastDeal[];
};

export type Backtest = { computed_at: string | null; watches: WatchBacktest[] };
export type DealStatus = "verified" | "unverified" | "failed";

// Data health (ticket 10): GET /data-health
export type SourceStatus = "ok" | "no_data" | "gated" | "failing" | "blocked";
export type SourceHealth = {
  source: string;
  status: SourceStatus;
  last_observation_at: string | null;
  observation_age_minutes: number | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  blocked: { blocked_at: string; reason: string } | null;
  gated_by: string[];
};
export type CoverageGap = { origin: string; destination: string; month: string; watch_ids: number[] };
export type SourceBacklog = {
  source: string;
  scheduled: number;
  scanned: number;
  failed: number;
  skipped: number;
  backlog: number;
};
export type SkippedTask = {
  source: string;
  origin: string;
  destination: string | null;
  month: string;
  priority: number;
  reason: string | null;
};
export type VerificationUse = {
  source: string;
  used_today: number;
  daily_quota: number | null;
  used_month: number;
  monthly_quota: number | null;
  outcomes: Record<"verified" | "failed" | "unverified", number>;
  reasons: Record<string, number>;
};
export type CheckFailure = {
  check_name: string;
  source: string;
  origin: string | null;
  detail: string;
  checked_at: string;
  since: string | null;
};
export type DataHealth = {
  checked_at: string;
  sources: SourceHealth[];
  coverage: { route_months: number; covered: number; gaps: CoverageGap[] };
  backlog: { planned_at: string | null; sources: SourceBacklog[]; skipped: SkippedTask[] };
  verification: VerificationUse[];
  checks: { active: CheckFailure[]; recent: CheckFailure[] };
};

// Watch assistant: a chat that proposes Watch specs the owner can create with one click.
export type Proposal = {
  id: string;
  reason: string;
  spec: WatchSpec;
  places: Place[];
  trip: TripResolution;
  resolved: { origins: number; destinations: number };
};
export type ChatTurn = { chat_id: number; reply: string; proposals: Proposal[] };

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
  resolveTripPattern: (trip_pattern: TripPreset) =>
    call<TripResolution>("/trip-patterns/resolve", json("POST", { trip_pattern })),
  agentStatus: () => call<{ enabled: boolean }>("/agent"),
  startChat: (text: string) => call<ChatTurn>("/agent/chats", json("POST", { text })),
  continueChat: (chatId: number, text: string) => call<ChatTurn>(`/agent/chats/${chatId}`, json("POST", { text })),
  listRoutes: () => call<Route[]>("/routes"),
  backtest: () => call<Backtest>("/backtest"),
  dataHealth: () => call<DataHealth>("/data-health"),
  routeHistory: (origin: string, destination: string, departure: string, returnDate?: string) => {
    const q = new URLSearchParams({ departure_date: departure });
    if (returnDate) q.set("return_date", returnDate);
    return call<RouteHistory>(
      `/routes/${encodeURIComponent(origin)}/${encodeURIComponent(destination)}/history?${q}`,
    );
  },
};
