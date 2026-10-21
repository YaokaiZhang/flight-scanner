"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Backtest, type Outcome, type WatchBacktest } from "@/lib/api";
import { formatDate, formatEur, formatInstant } from "@/lib/format";

const OUTCOME_LABEL: Record<Outcome, string> = {
  real_dip: "Real dip",
  stayed_low: "Stayed low",
  pending: "Pending",
  inconclusive: "Inconclusive",
  unjudged: "No Baseline",
};

const OUTCOME_TAG: Record<Outcome, string> = {
  real_dip: "verified",
  stayed_low: "fail",
  pending: "plain",
  inconclusive: "off",
  unjudged: "off",
};

const pct = (p: number | null) => (p === null ? "—" : `${Math.round(p * 100)}%`);
const bucketLabel = (from: number, to: number | null) => (to === null ? `${from}%+` : `${from}–${to}%`);

function OutcomeTag({ outcome }: { outcome: Outcome }) {
  return <span className={`tag ${OUTCOME_TAG[outcome]}`}>{OUTCOME_LABEL[outcome]}</span>;
}

function Distribution({ w }: { w: WatchBacktest }) {
  const most = Math.max(1, ...w.pct_below_baseline.buckets.map((b) => b.deals));
  return (
    <table className="bars" aria-label="Deals by % below Baseline">
      <tbody>
        {w.pct_below_baseline.buckets.map((b) => (
          <tr key={b.from_pct}>
            <th scope="row">{bucketLabel(b.from_pct, b.to_pct)}</th>
            <td>
              <span className="bar" style={{ width: `${(b.deals / most) * 100}%` }} />
            </td>
            <td className="num">{b.deals}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Inspector({ w }: { w: WatchBacktest }) {
  const judged = w.outcomes.real_dip + w.outcomes.stayed_low;
  return (
    <>
      <section>
        <h2 className="widget-label">Precision</h2>
        <div className="data-point">{pct(w.precision)}</div>
        <p className="data-desc">
          {judged
            ? <><em>{w.outcomes.real_dip}</em> of {judged} judged Deals went back toward their Baseline.</>
            : "No Deal has been judged yet: each needs a few days of later prices."}
          {w.outcomes.pending ? ` ${w.outcomes.pending} still pending.` : ""}
        </p>
        <p className="meta">Sensitivity {w.sensitivity_pct}% · tune it in the Watch editor.</p>
      </section>
      <section>
        <h2 className="widget-label">Alert rate</h2>
        <div className="data-point">{w.alerts_per_week}<small>per week</small></div>
        <p className="data-desc">
          <em>{w.alerts}</em> Alert{w.alerts === 1 ? "" : "s"} over {w.weeks} week{w.weeks === 1 ? "" : "s"}
        </p>
      </section>
      <section>
        <h2 className="widget-label">% below Baseline</h2>
        <Distribution w={w} />
        {w.pct_below_baseline.median !== null && (
          <p className="meta">Median −{w.pct_below_baseline.median}%</p>
        )}
      </section>
      <section>
        <h2 className="widget-label">Feedback by outcome</h2>
        <table className="compact" aria-label="Feedback by outcome">
          <thead>
            <tr><th>Outcome</th><th className="num">Good</th><th className="num">Bad</th><th className="num">Unrated</th></tr>
          </thead>
          <tbody>
            {w.feedback.by_outcome
              .filter((f) => f.up + f.down + f.unrated > 0)
              .map((f) => (
                <tr key={f.outcome}>
                  <td>{OUTCOME_LABEL[f.outcome]}</td>
                  <td className="num">{f.up}</td>
                  <td className="num">{f.down}</td>
                  <td className="num">{f.unrated}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

export function BacktestView() {
  const [data, setData] = useState<Backtest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    api.backtest().then(
      (b) => {
        setData(b);
        setSelected((s) => s ?? b.watches.find((w) => w.deals > 0)?.watch_id ?? b.watches[0]?.watch_id ?? null);
      },
      (e: ApiError) => setError(`Could not load the backtest (${e.status ?? "network"})`),
    );
  }, []);

  const current = data?.watches.find((w) => w.watch_id === selected) ?? null;
  const totals = data?.watches.reduce(
    (t, w) => ({ dips: t.dips + w.outcomes.real_dip, judged: t.judged + w.outcomes.real_dip + w.outcomes.stayed_low }),
    { dips: 0, judged: 0 },
  );

  return (
    <>
      <main className="main-canvas" id="main" tabIndex={-1}>
        <header className="page-head">
          <div>
            <h1>Backtest</h1>
            <p className="lede">
              {totals && totals.judged
                ? <><b>{totals.dips}</b> of {totals.judged} judged Deals were real dips</>
                : "Was each Deal a real dip? Judged from the prices seen after it"}
              {data?.computed_at ? ` · as of ${formatInstant(data.computed_at)}` : ""}
            </p>
          </div>
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {data && data.watches.length === 0 && (
          <div className="empty"><strong>No Watches yet</strong>Create one to start collecting Deals.</div>
        )}
        {data && data.watches.length > 0 && (
          <div className="table-wrap">
            <table aria-label="Backtest per Watch">
              <thead>
                <tr>
                  <th>Watch</th><th className="num">Deals</th><th className="num">Dips</th>
                  <th className="num">Low</th><th className="num">Precision</th>
                  <th className="num">Alerts/wk</th><th className="num">Median</th><th className="num">Good/bad</th>
                </tr>
              </thead>
              <tbody>
                {data.watches.map((w) => (
                  <tr key={w.watch_id} className={`selectable${w.status !== "active" ? " paused" : ""}`} aria-selected={w.watch_id === selected}>
                    <td className="row-title">
                      <button type="button" onClick={() => setSelected(w.watch_id)}>{w.watch_name}</button>
                      <div className="sub">sensitivity {w.sensitivity_pct}% · {w.status}</div>
                    </td>
                    <td data-label="Deals" className="num">{w.deals}</td>
                    <td data-label="Real dips" className="num">{w.outcomes.real_dip}</td>
                    <td data-label="Stayed low" className="num">{w.outcomes.stayed_low}</td>
                    <td data-label="Precision" className="num">{pct(w.precision)}</td>
                    <td data-label="Alerts per week" className="num">{w.alerts_per_week}</td>
                    <td data-label="Median below Baseline" className="num">
                      {w.pct_below_baseline.median === null ? "—" : `−${w.pct_below_baseline.median}%`}
                    </td>
                    <td data-label="Rated good / bad" className="num">{w.feedback.up} / {w.feedback.down}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {current && current.past_deals.length > 0 && (
          <>
            <h2 className="section-head">Past Deals · {current.watch_name}</h2>
            <div className="table-wrap">
              <table aria-label="Past Deals">
                <thead>
                  <tr>
                    <th>Trip</th><th className="num">Deal</th><th className="num">Baseline</th>
                    <th className="num">Highest after</th><th>Outcome</th><th>Rated</th>
                  </tr>
                </thead>
                <tbody>
                  {current.past_deals.map((d) => (
                    <tr key={d.deal_id}>
                      <td className="row-title">
                        {d.origin} → {d.destination}
                        <div className="sub">
                          {formatDate(d.outbound_date)}
                          {d.return_date ? ` → ${formatDate(d.return_date)}` : " · one way"} · found {formatInstant(d.detected_at)}
                        </div>
                      </td>
                      <td data-label="Deal" className="num">
                        {formatEur(d.price_per_adult_eur)}
                        {d.pct_below_baseline !== null && <div className="sub">−{d.pct_below_baseline}%</div>}
                      </td>
                      <td data-label="Baseline" className="num">
                        {d.baseline_per_adult_eur === null ? "—" : formatEur(d.baseline_per_adult_eur)}
                        {d.baseline_tier && <div className="sub">{d.baseline_tier}</div>}
                      </td>
                      <td data-label="Highest after" className="num">
                        {d.highest_later_price_per_adult_eur === null ? "—" : formatEur(d.highest_later_price_per_adult_eur)}
                        <div className="sub">{d.later_observation_days} day{d.later_observation_days === 1 ? "" : "s"} seen</div>
                      </td>
                      <td data-label="Outcome"><OutcomeTag outcome={d.outcome} /></td>
                      <td data-label="Rated">{d.rating === "up" ? "Good" : d.rating === "down" ? "Bad" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
      <aside className="inspector" aria-label="Inspector" aria-live="polite">
        {current ? <Inspector w={current} /> : <p className="meta">Select a Watch to inspect its backtest.</p>}
      </aside>
    </>
  );
}
