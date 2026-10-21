"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type CheckFailure,
  type DataHealth,
  type SourceHealth,
  type SourceStatus,
  type VerificationUse,
} from "@/lib/api";
import { formatInstant, formatMinutes } from "@/lib/format";

const STATUS_LABEL: Record<SourceStatus, string> = {
  ok: "Healthy",
  no_data: "No data",
  gated: "Gated",
  failing: "Failing",
  blocked: "Blocked",
};

const STATUS_TAG: Record<SourceStatus, string> = {
  ok: "verified",
  no_data: "off",
  gated: "unverified",
  failing: "fail",
  blocked: "fail",
};

const CHECK_LABEL: Record<string, string> = {
  zero_rows: "Empty scan",
  price_jump: "Price-level jump",
  stale_data: "Stale data",
};

const REASON_LABEL: Record<string, string> = {
  live_deal: "still a Deal",
  live_not_a_deal: "no longer a Deal",
  not_found: "not found live",
  budget_exhausted: "budget spent",
  no_verifier: "no verifier",
  verifier_error: "verifier error",
};

const when = (iso: string | null) => (iso === null ? "—" : formatInstant(iso));
const age = (minutes: number | null) => (minutes === null ? "never" : `${formatMinutes(minutes)} ago`);
const slice = (c: CheckFailure) => `${c.source} · ${c.origin ?? "all origins"}`;

function SourceRow({ s }: { s: SourceHealth }) {
  return (
    <tr>
      <td className="row-title">
        {s.source}
        {s.gated_by.length > 0 && (
          <div className="sub">gated by {s.gated_by.map((c) => CHECK_LABEL[c] ?? c).join(", ")}</div>
        )}
      </td>
      <td data-label="Status"><span className={`tag ${STATUS_TAG[s.status]}`}>{STATUS_LABEL[s.status]}</span></td>
      <td data-label="Newest price">
        {age(s.observation_age_minutes)}
        {s.last_observation_at && <div className="sub">{when(s.last_observation_at)}</div>}
      </td>
      <td data-label="Last success">{when(s.last_success_at)}</td>
      <td data-label="Last failure">
        {when(s.last_failure_at)}
        {s.blocked ? (
          <div className="sub">blocked: {s.blocked.reason}</div>
        ) : (
          s.last_error && <div className="sub">{s.last_error}</div>
        )}
      </td>
    </tr>
  );
}

function Budget({ v }: { v: VerificationUse }) {
  const reasons = Object.entries(v.reasons);
  return (
    <section>
      <h2 className="widget-label">Verification budget · {v.source}</h2>
      <div className={`data-point${v.daily_quota !== null && v.used_today >= v.daily_quota ? " amber" : ""}`}>
        {v.used_today}
        <small>{v.daily_quota === null ? "calls today" : `of ${v.daily_quota} today`}</small>
      </div>
      <p className="data-desc">
        <em>{v.used_month}</em>
        {v.monthly_quota === null ? " live calls this month" : ` of ${v.monthly_quota} live calls this month`}
      </p>
      <p className="meta">
        This month: {v.outcomes.verified} verified · {v.outcomes.failed} failed · {v.outcomes.unverified} unverified
        {reasons.length > 0 && <> ({reasons.map(([r, n]) => `${n} ${REASON_LABEL[r] ?? r}`).join(", ")})</>}
      </p>
    </section>
  );
}

function Inspector({ data }: { data: DataHealth }) {
  return (
    <>
      {data.verification.length === 0 ? (
        <section>
          <h2 className="widget-label">Verification budget</h2>
          <p className="meta">No Verification source is configured: every Deal is alerted Unverified.</p>
        </section>
      ) : (
        data.verification.map((v) => <Budget key={v.source} v={v} />)
      )}
      <section>
        <h2 className="widget-label">Coverage</h2>
        <div className="data-point">
          {data.coverage.covered}
          <small>of {data.coverage.route_months} route-months</small>
        </div>
        <p className="data-desc">priced by a source in the last 7 days</p>
      </section>
      <section>
        <h2 className="widget-label">Recent check failures</h2>
        {data.checks.recent.length === 0 ? (
          <p className="meta">No data-quality check failed in the last 7 days.</p>
        ) : (
          <table className="compact" aria-label="Recent check failures">
            <tbody>
              {data.checks.recent.map((c, i) => (
                <tr key={`${c.checked_at}-${c.check_name}-${c.source}-${c.origin}-${i}`}>
                  <td>
                    {CHECK_LABEL[c.check_name] ?? c.check_name} · {slice(c)}
                    <div className="sub">{formatInstant(c.checked_at)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

export function DataHealthView() {
  const [data, setData] = useState<DataHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dataHealth().then(setData, (e: ApiError) =>
      setError(`Could not load data health (${e.status ?? "network"})`),
    );
  }, []);

  const troubled = data?.sources.filter((s) => s.status !== "ok").length ?? 0;
  const backlog = data?.backlog.sources.reduce((n, s) => n + s.backlog, 0) ?? 0;

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Data health</h1>
            <p className="lede">
              {data ? (
                <>
                  <b>{data.sources.length - troubled}</b> of {data.sources.length} source
                  {data.sources.length === 1 ? "" : "s"} healthy · <b>{data.checks.active.length}</b> gate
                  {data.checks.active.length === 1 ? "" : "s"} in force · <b>{data.coverage.gaps.length}</b> coverage gap
                  {data.coverage.gaps.length === 1 ? "" : "s"} · as of {formatInstant(data.checked_at)}
                </>
              ) : (
                "Can the scanner be trusted right now?"
              )}
            </p>
          </div>
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {data && (
          <>
            <h2 className="section-head">Sources</h2>
            {data.sources.length === 0 ? (
              <div className="empty"><strong>No source has scanned yet</strong>Prices appear after the first scan.</div>
            ) : (
              <div className="table-wrap">
                <table aria-label="Sources">
                  <thead>
                    <tr><th>Source</th><th>Status</th><th>Newest price</th><th>Last success</th><th>Last failure</th></tr>
                  </thead>
                  <tbody>{data.sources.map((s) => <SourceRow key={s.source} s={s} />)}</tbody>
                </table>
              </div>
            )}

            <h2 className="section-head">Data-quality gates</h2>
            {data.checks.active.length === 0 ? (
              <div className="empty"><strong>No gate in force</strong>Every slice&rsquo;s prices can produce Deals.</div>
            ) : (
              <div className="table-wrap">
                <table aria-label="Data-quality gates">
                  <thead><tr><th>Check</th><th>Slice</th><th>Since</th><th>Why</th></tr></thead>
                  <tbody>
                    {data.checks.active.map((c) => (
                      <tr key={`${c.check_name}-${c.source}-${c.origin}`}>
                        <td className="row-title">{CHECK_LABEL[c.check_name] ?? c.check_name}</td>
                        <td data-label="Slice">{slice(c)}</td>
                        <td data-label="Since">{when(c.since)}</td>
                        <td data-label="Why">{c.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <h2 className="section-head">Coverage gaps</h2>
            {data.coverage.gaps.length === 0 ? (
              <div className="empty">
                <strong>No gaps</strong>
                {data.coverage.route_months ? "Every demanded route-month has recent prices." : "No Watch demands prices yet."}
              </div>
            ) : (
              <div className="table-wrap">
                <table aria-label="Coverage gaps">
                  <thead><tr><th>Route</th><th>Month</th><th className="num">Watches</th></tr></thead>
                  <tbody>
                    {data.coverage.gaps.map((g) => (
                      <tr key={`${g.origin}-${g.destination}-${g.month}`}>
                        <td className="row-title">{g.origin} → {g.destination}</td>
                        <td data-label="Month">{g.month}</td>
                        <td data-label="Watches" className="num">{g.watch_ids.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <h2 className="section-head">
              Scan backlog{data.backlog.planned_at ? ` · plan of ${formatInstant(data.backlog.planned_at)}` : ""}
            </h2>
            {data.backlog.sources.length === 0 ? (
              <div className="empty"><strong>No scan planned yet</strong>The planner runs with every scan.</div>
            ) : (
              <>
                <div className="table-wrap">
                  <table aria-label="Scan backlog">
                    <thead>
                      <tr>
                        <th>Source</th><th className="num">Scanned</th><th className="num">Failed</th>
                        <th className="num">Skipped</th><th className="num">Backlog</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.backlog.sources.map((s) => (
                        <tr key={s.source}>
                          <td className="row-title">{s.source}</td>
                          <td data-label="Scanned" className="num">{s.scanned + s.scheduled}</td>
                          <td data-label="Failed" className="num">{s.failed}</td>
                          <td data-label="Skipped" className="num">{s.skipped}</td>
                          <td data-label="Over budget" className="num">{s.backlog}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="meta">{backlog} task{backlog === 1 ? "" : "s"} waiting for budget.</p>
                {data.backlog.skipped.length > 0 && (
                  <div className="table-wrap">
                    <table aria-label="Skipped scan tasks">
                      <thead><tr><th>Task</th><th>Month</th><th className="num">Priority</th><th>Reason</th></tr></thead>
                      <tbody>
                        {data.backlog.skipped.map((t, i) => (
                          <tr key={`${t.source}-${t.origin}-${t.destination}-${t.month}-${i}`}>
                            <td className="row-title">
                              {t.origin} → {t.destination ?? "anywhere"}
                              <div className="sub">{t.source}</div>
                            </td>
                            <td data-label="Month">{t.month}</td>
                            <td data-label="Priority" className="num">{t.priority.toFixed(2)}</td>
                            <td data-label="Reason">{t.reason ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>
      <aside className="inspector" aria-label="Inspector" aria-live="polite">
        {data ? <Inspector data={data} /> : <p className="meta">Loading…</p>}
      </aside>
    </>
  );
}
