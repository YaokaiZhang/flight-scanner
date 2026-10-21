---
version: 1
slug: "docs-design-prototype-index-html"
primary_target: "docs/design/prototype/index.html"
related_targets: []
---

# Flight Scanner app shell — surface brief

Scope: the whole owner-facing web UI (Deals, Watches, Route explorer, Data health, Backtest), prototyped as one static page for the Next.js build. Mode: Operate.

Job: the owner checks a Deal that an Alert pointed to, judges it against its Baseline, books it or rates it, tunes Watches, and confirms the system can be trusted.

Constraints: single owner, desktop first, but the Deals feed must work on a phone (opened from an Alert). Prototype data is synthetic and labelled.

## Direction contract

THESIS: Every Deal is a measured drawing. The fare is an ink mark set against its Baseline, drawn in construction lines, with an annotation that states the gap. This replaces the category default of a card grid with a red "−45%" badge.

OWN-WORLD: The owner-pinned "Blue Sky // Process Board". Paper #fcfcfc with a 40px dot grid. Ink #0076FF for prices, selection, and the line being measured. Graphite #4b4b4b for text. Construction #d1d1d1 for rules and dashed guides only, never for text. JetBrains Mono for all data. Playfair Display italic appears only in the hand-drawn wordmark. Outlined marker buttons tilt −1° on hover. Circle-bullet labels on the inspector rail.

STORY: The owner sees at a glance which Deals are real (the Verified ones), how far each sits below normal, and why. They select one, read its full evidence in the inspector, then book it or rate it.

FIRST VIEWPORT: Rotated vertical nav (DEALS active), with the hand-drawn "fs" logo on top. The main canvas holds the Deals feed. Each row shows route, dates, and price, plus a baseline ruler: a dashed band for the Baseline ± MAD and an ink tick for the price, with a leader-line callout giving % below. A 350px inspector rail on the right shows the selected Deal: price, Baseline tier, Verified state, legs, Deal context, Book, and 👍/👎. The primary action is Book in the inspector.

FORM: Pinned by the owner (reference study, adapted for a working tool). No roll. Seed key: none (pinned).

SIGNATURE: Baseline rulers with leader-line annotations, reused on the Route explorer chart and as the Trip-pattern dimension line in the Watch editor. Motion: the ink stroke draws once when a view opens.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
