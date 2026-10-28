"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PAGES = [
  { href: "/deals", label: "Deals" },
  { href: "/watches", label: "Watches" },
  { href: "/routes", label: "Routes" },
  { href: "/backtest", label: "Backtest" },
  { href: "/data-health", label: "Data health" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="nav-vertical" aria-label="Primary">
      <Link className="brand" href="/deals" aria-label="Flight Scanner, Deals">
        {/* hand-drawn mark: felt-tip "fs" under a dashed flight path, with a plane at its end */}
        <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
          <path d="M4 60 Q30 66 58 10" stroke="var(--graphite)" strokeWidth="0.8" strokeDasharray="1.5 3" strokeLinecap="round" />
          <path d="M22 54 C21 40 22 30 22 23 C22 13 27 9 34 9 C39 9 41.5 11 42.5 14" stroke="var(--ink)" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13 29 C18 28.2 25 27.8 32 28.4" stroke="var(--ink)" strokeWidth="4.5" strokeLinecap="round" />
          <path d="M53 33 C49 28.5 41 28.5 40 33.5 C39 38.5 49 39 51.5 44 C54 49.5 47 55 39.5 50.5" stroke="var(--ink)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6 0 C6 -0.7 5.2 -1 4.4 -1 L1.4 -1 L-1.6 -5.6 L-3 -5.6 L-1.2 -1 L-4 -1 L-5.4 -2.8 L-6.4 -2.8 L-5.6 0 L-6.4 2.8 L-5.4 2.8 L-4 1 L-1.2 1 L-3 5.6 L-1.6 5.6 L1.4 1 L4.4 1 C5.2 1 6 0.7 6 0 Z" transform="translate(57 11) rotate(-63)" fill="var(--ink)" />
        </svg>
        <span className="wordmark">Flight Scanner</span>
      </Link>
      <ul className="nav-list">
        {PAGES.map((p) => (
          <li key={p.href}>
            <Link
              className="nav-item"
              href={p.href}
              aria-current={pathname.startsWith(p.href) ? "page" : undefined}
            >
              {p.label}
            </Link>
          </li>
        ))}
      </ul>
      <div className="nav-foot">HEL 60.317°N 24.963°E</div>
    </nav>
  );
}
