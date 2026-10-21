# Product

<!-- impeccable:product-schema 1 -->

_Derived from `docs/PRD.md` (agreed 2026-10-17) and `CONTEXT.md`; vocabulary follows CONTEXT.md._

## Platform

web

## Stack

Decided in the PRD: Next.js web UI over a FastAPI API that reads only from the marts layer, served from Docker Compose on `verda` and bound to localhost (reached through an SSH tunnel). The static HTML prototype in `docs/design/prototype/` is a design reference for that build, not a second front end.

## Users

A single owner in Helsinki. They set up Watches through the web UI on a desktop over an SSH tunnel. Alerts reach them on their phone through Telegram and by email, and they come back to the UI to check a Deal, rate it, and tune their Watches. There are no other users, no sign-up, and no authentication in v1.

## Product Purpose

Flight Scanner keeps watching flight prices for the trips the owner cares about. It sends an Alert when a fare is significantly below what that trip normally costs, for example when HEL→Egypt in November usually costs about €200 return and a €100 fare appears. Success means a few Alerts per Watch per week, each one a real dip, sent within one scan cycle, at €0/month.

## Positioning

Fares are judged against a learned Baseline instead of a fixed "below €X" limit. The scanner covers wide, flexible searches (Regions with Exclusions, rolling Trip patterns, Round trips composed from two one-way tickets) using only free sources: cached discovery plus a small budget of live Verification. Every Deal shows why it counts: the Baseline and its tier, the percentage below it, and whether it was Verified.

## Operating Context

- The main loop: an Alert arrives on the phone, the owner opens the Deals feed, inspects the Deal against its Baseline, books it through the source's link, and rates it 👍/👎.
- Setting up a Watch: pick Places with include/exclude chips and the Region tree, choose a Trip-pattern preset and see the resolved window, then set adults, threshold, sensitivity, and delivery.
- Trust checks: the Route explorer (price history against the Baseline band), Data health (freshness, coverage, planner backlog, verification budget, asset-check failures), and Backtest (precision, Alert rate, feedback).

## Capabilities and Constraints

- Pages: Watches, Deals, Route explorer, Data health, Backtest (PRD §5.12).
- Deals are Verified or Unverified. Unverified Deals must be clearly labelled. "2 separate tickets" is shown when it applies.
- Baseline tiers: route → destination country → Price insight → provisional (low confidence). Each Deal records the tier it was judged against.
- Verification budget: 250 SerpApi searches per month (~8/day).
- Prices are in EUR per adult, and total for N adults where relevant. Prices are not baggage-normalised.
- Out of scope: booking, payment, multiple users, SMS, and Self-transfer.

## Brand Commitments

- Name: Flight Scanner.
- Visual reference pinned by the owner (2026-10-21): the "Blue Sky // Process Board" study. That means paper ground with a dot grid, ink blue #0076FF, graphite text, mono type, a vertical nav, an inspector rail, annotation callouts, and a hand-drawn stroked logo. Adapted for a working tool: normal cursors, real data in the coordinate labels, and accessible contrast.

## Evidence on Hand

No real fare data, screenshots, or logo assets exist yet. Prototype data is synthetic and must be labelled as such. Never present it as observed prices.

## Product Principles

1. Show the evidence behind every Deal: Baseline, tier, % below, and Verified status, side by side.
2. Be honest about uncertainty: Unverified Deals, provisional Baselines, and coverage gaps are shown, never hidden.
3. Express trips the way the owner thinks about them, and always show the resolved window.
4. A quiet feed is the goal. Signal beats volume.

## Accessibility & Inclusion

No product-specific requirement beyond WCAG AA contrast and full keyboard operability.
