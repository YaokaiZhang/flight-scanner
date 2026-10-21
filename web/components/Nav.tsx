"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PAGES = [
  { href: "/deals", label: "Deals" },
  { href: "/watches", label: "Watches" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="nav-vertical" aria-label="Primary">
      <Link className="brand" href="/deals" aria-label="Flight Scanner, Deals">
        {/* hand-drawn mark: felt-tip "fs" with its flight path and construction circle */}
        <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
          <path d="M4 60 Q30 66 58 10" stroke="var(--graphite)" strokeWidth="0.8" strokeDasharray="1.5 3" strokeLinecap="round" />
          <path d="M22 54 C21 40 22 30 22 23 C22 13 27 9 34 9 C39 9 41.5 11 42.5 14" stroke="var(--ink)" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13 29 C18 28.2 25 27.8 32 28.4" stroke="var(--ink)" strokeWidth="4.5" strokeLinecap="round" />
          <path d="M53 33 C49 28.5 41 28.5 40 33.5 C39 38.5 49 39 51.5 44 C54 49.5 47 55 39.5 50.5" stroke="var(--ink)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="42.5" cy="14" r="7" stroke="var(--graphite)" strokeWidth="0.6" strokeDasharray="2 2" />
          <line x1="47.5" y1="9" x2="56" y2="1" stroke="var(--graphite)" strokeWidth="0.8" />
          <circle cx="58" cy="10" r="2" fill="var(--ink)" />
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
