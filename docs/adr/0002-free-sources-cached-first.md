# Free data sources only: cached-first discovery, budgeted live verification

Amadeus Self-Service shut down in July 2026, Kiwi Tequila and Skyscanner are partner-only, and per-itinerary live APIs (Duffel, SerpApi Google Flights, paid scrapers) cost far more than a personal project should. We use only free sources: Travelpayouts/Aviasales cached data for broad discovery (Leg prices and Round-trip prices, up to ~48h old), and the SerpApi free tier (250 searches/month, ~8/day) to verify the top Candidates live. This mirrors how metasearch sites answer "anywhere / whole month" queries — from cache — at small scale. When the verification budget is spent, Deals are still alerted but marked Unverified.

## Considered options

- **Paid SerpApi plans ($25–75/month)** for live round-trip discovery — rejected on cost.
- **An AI agent with web search as a price source** — rejected: fares are rendered dynamically and are not in search indexes, so it yields stale marketing prices or hallucinations. An agent is used only for Deal context ("why is this cheap").
- **Self-built large-scale scraping from the cloud** — rejected: Google/airline ToS, legal precedent (Ryanair v. Booking.com, 2024), and it would require bot-protection evasion, which is out of scope for this project.

## Consequences

- Unofficial Ryanair/Wizz calendar adapters exist as optional sources: low request rate, no bot-protection bypass, shipped **disabled by default** in the public repository with a ToS note.
- Scan cadence is per source (cached data every 30–60 min; airline adapters every 1–2 h), not a global "every 5 minutes", because re-reading a cache more often yields the same answer.
