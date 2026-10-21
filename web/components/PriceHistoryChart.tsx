"use client";

import { useEffect, useRef, useState } from "react";
import type { HistoryPoint } from "@/lib/api";
import { formatEur } from "@/lib/format";

// Change-only price history drawn as a step line: each row holds its price from valid_from until
// the next change (or until it was last seen, while current). Route-chart grammar from DESIGN.md:
// dashed construction gridlines with pencil € labels, a 1.5px ink line, paper-filled ink dots at
// each change, a solid graphite x-axis with 4px ticks. The Baseline band arrives with Baselines.

const H = 300;
const M = { l: 52, r: 20, t: 24, b: 34 };

const dayFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Europe/Helsinki" });
const timeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Helsinki",
});

function niceStep(span: number) {
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
}

type Segment = { source: string; from: number; to: number; price: number; current: boolean };

export function PriceHistoryChart({ points, label }: { points: HistoryPoint[]; label: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const segs: Segment[] = points.map((p) => ({
    source: p.source,
    from: Date.parse(p.valid_from),
    to: Date.parse(p.valid_to ?? p.last_observed_at),
    price: p.price_per_adult_eur,
    current: p.valid_to === null,
  }));
  const t0 = Math.min(...segs.map((s) => s.from));
  let t1 = Math.max(...segs.map((s) => s.to));
  if (t1 - t0 < 3_600_000) t1 = t0 + 3_600_000; // at least an hour wide
  const prices = segs.map((s) => s.price);
  const pad = Math.max(10, (Math.max(...prices) - Math.min(...prices)) * 0.25);
  const step = niceStep(Math.max(...prices) - Math.min(...prices) + 2 * pad);
  const lo = Math.max(0, Math.floor((Math.min(...prices) - pad) / step) * step);
  const hi = Math.ceil((Math.max(...prices) + pad) / step) * step;

  const x = (t: number) => M.l + ((t - t0) / (t1 - t0)) * (w - M.l - M.r);
  const y = (v: number) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);

  const sources = [...new Set(segs.map((s) => s.source))];
  const paths = sources.map((src, i) => {
    const mine = segs.filter((s) => s.source === src);
    const d = mine
      .map((s, k) => `${k ? "L" : "M"}${x(s.from).toFixed(1)} ${y(s.price).toFixed(1)} H${x(s.to).toFixed(1)}`)
      .join(" ");
    return { src, d, primary: i === 0, mine };
  });

  const grid: number[] = [];
  for (let v = lo; v <= hi + 1e-9; v += step) grid.push(v);
  const multiDay = t1 - t0 > 2 * 86_400_000;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + f * (t1 - t0));
  const latest = segs.reduce((a, b) => (b.from > a.from ? b : a));

  return (
    <div className="chart" ref={wrap}>
      <svg viewBox={`0 0 ${w} ${H}`} height={H} role="img" aria-label={label}>
        {grid.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={w - M.r} y1={y(v)} y2={y(v)} stroke="var(--construction)" strokeWidth={0.6} strokeDasharray="3 4" />
            <text x={M.l - 8} y={y(v) + 3} textAnchor="end">{formatEur(v)}</text>
          </g>
        ))}
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={x(t)} x2={x(t)} y1={H - M.b} y2={H - M.b + 4} stroke="var(--graphite)" strokeWidth={0.8} />
            <text x={x(t)} y={H - M.b + 18} textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}>
              {(multiDay ? dayFmt : timeFmt).format(new Date(t))}
            </text>
          </g>
        ))}
        {paths.map((p) => (
          <g key={p.src}>
            <path
              className={p.primary ? "ink-path" : undefined}
              d={p.d}
              pathLength={p.primary ? 1 : undefined}
              fill="none"
              stroke={p.primary ? "var(--ink)" : "var(--graphite)"}
              strokeWidth={p.primary ? 1.5 : 1}
              strokeDasharray={p.primary ? undefined : "4 3"}
              strokeLinejoin="round"
            />
            {p.mine.map((s) =>
              p.primary ? (
                <circle key={s.from} cx={x(s.from)} cy={y(s.price)} r={2.5} fill="var(--paper)" stroke="var(--ink)" strokeWidth={1} />
              ) : (
                <rect key={s.from} x={x(s.from) - 3} y={y(s.price) - 3} width={6} height={6} fill="var(--paper)" stroke="var(--graphite)" strokeWidth={1} />
              ),
            )}
          </g>
        ))}
        <circle cx={x(latest.from)} cy={y(latest.price)} r={13} fill="none" stroke="var(--graphite)" strokeWidth={0.6} strokeDasharray="2 2" />
        <text
          x={Math.min(x(latest.from) + 18, w - M.r)}
          y={Math.max(y(latest.price) - 18, M.t)}
          textAnchor={x(latest.from) + 150 > w ? "end" : "start"}
          className="callout"
        >
          {latest.current ? "NOW " : ""}{formatEur(latest.price)}
        </text>
        <line x1={M.l} x2={w - M.r} y1={H - M.b} y2={H - M.b} stroke="var(--graphite)" strokeWidth={1} />
      </svg>
      <div className="legend">
        {paths.map((p) => (
          <span key={p.src}>
            <svg viewBox="0 0 18 10" aria-hidden="true">
              <path d="M0 5h18" stroke={p.primary ? "var(--ink)" : "var(--graphite)"} strokeWidth={p.primary ? 1.5 : 1} strokeDasharray={p.primary ? undefined : "4 3"} />
            </svg>
            {p.src}
          </span>
        ))}
        <span>One step per price change; flat while unchanged</span>
      </div>
    </div>
  );
}
