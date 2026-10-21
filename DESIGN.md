---
name: Flight Scanner
description: A process board where every Deal is measured in ink against its Baseline.
colors:
  ink: "#0076ff"
  ink-deep: "#0058c4"
  swash: "rgba(0, 118, 255, 0.12)"
  swash-strong: "rgba(0, 118, 255, 0.22)"
  swash-faint: "rgba(0, 118, 255, 0.05)"
  amber: "#8a5300"
  amber-wash: "rgba(196, 122, 0, 0.10)"
  red: "#b42318"
  paper: "#fcfcfc"
  graphite: "#4b4b4b"
  pencil: "#6b6b6b"
  construction: "#d1d1d1"
typography:
  display:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "34px"
    fontWeight: 300
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "24px"
    fontWeight: 300
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "22px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.6
    letterSpacing: "-0.01em"
  body:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "tnum"
  body-small:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "0.1em"
  wordmark:
    fontFamily: "'Playfair Display', Georgia, serif"
    fontSize: "19px"
    fontWeight: 700
    letterSpacing: "0.01em"
rounded:
  none: "0px"
  dot: "50%"
spacing:
  xs: "4px"
  sm: "6px"
  md: "12px"
  lg: "18px"
  xl: "28px"
  gutter: "32px"
  rail: "40px"
components:
  button-marker:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 18px"
  button-marker-hover:
    backgroundColor: "{colors.swash}"
    textColor: "{colors.ink-deep}"
  button-marker-primary:
    backgroundColor: "transparent"
    textColor: "{colors.ink-deep}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 18px"
  button-marker-primary-hover:
    backgroundColor: "{colors.swash-strong}"
    textColor: "{colors.ink-deep}"
  button-marker-danger:
    backgroundColor: "transparent"
    textColor: "{colors.red}"
    padding: "8px 4px"
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    size: "36px"
  button-icon-pressed:
    backgroundColor: "{colors.swash}"
    textColor: "{colors.ink-deep}"
  segmented-option:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    typography: "{typography.label}"
    padding: "6px 12px"
  segmented-option-pressed:
    backgroundColor: "{colors.swash}"
    textColor: "{colors.ink-deep}"
  input-underline:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "6px 2px"
  input-underline-focus:
    backgroundColor: "{colors.swash}"
  tag-verified:
    backgroundColor: "transparent"
    textColor: "{colors.ink-deep}"
    rounded: "{rounded.none}"
    padding: "2px 7px"
  tag-unverified:
    backgroundColor: "{colors.amber-wash}"
    textColor: "{colors.amber}"
    rounded: "{rounded.none}"
    padding: "2px 7px"
  tag-plain:
    backgroundColor: "transparent"
    textColor: "{colors.pencil}"
    padding: "2px 7px"
  tag-drop:
    backgroundColor: "{colors.swash}"
    textColor: "{colors.ink-deep}"
    padding: "2px 7px"
  tag-off:
    backgroundColor: "transparent"
    textColor: "{colors.pencil}"
    padding: "2px 7px"
  tag-fail:
    backgroundColor: "transparent"
    textColor: "{colors.red}"
    padding: "2px 7px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "3px 4px 3px 9px"
  chip-exclude:
    backgroundColor: "transparent"
    textColor: "{colors.pencil}"
  nav-item:
    textColor: "{colors.pencil}"
    typography: "{typography.label}"
    padding: "4px 2px"
  nav-item-active:
    textColor: "{colors.ink-deep}"
  deal-row:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    padding: "18px 12px"
  deal-row-hover:
    backgroundColor: "{colors.swash-faint}"
  deal-row-selected:
    backgroundColor: "{colors.swash}"
    textColor: "{colors.ink-deep}"
  data-point:
    textColor: "{colors.ink}"
    typography: "{typography.display}"
  data-point-provisional:
    textColor: "{colors.amber}"
---

# Design System: Flight Scanner

## Overview

**Creative North Star: "The Process Board"**

Flight Scanner is drawn, not decorated. The ground is near-white drafting paper with a 40px dot grid; everything on it is either a construction line (light grey guides, dashed bands, rulers), graphite writing, or a single blue ink mark that records the thing being measured. A fare is never a badge: it is a tick on a ruler, set against a dashed Baseline band, with a dimension line and a callout that state the gap. The same drafting grammar carries through every view, so a price chart, a trip window, a budget meter and a histogram all read as sheets from one board.

Density is that of a working instrument: one monospaced family at small sizes (11 to 13px for nearly all text), tabular numerals throughout, generous air between inspector sections, and hairline rules instead of containers. Personality comes from three small human touches, kept deliberately rare: the hand-drawn felt-tip "fs" logo with its dashed flight path and construction circle, the italic serif wordmark, and outlined marker buttons that tilt a degree when touched. The world is adapted from the owner-pinned "Blue Sky // Process Board" study for daily use: standard cursors, coordinate labels that carry real data (scan time, host, tunnel), and WCAG AA contrast on every piece of text.

Implementation in Next.js: carry the frontmatter colours, fonts, ease and gutter as CSS custom properties on `:root` in the global stylesheet, under the same short names the prototype uses (`--paper`, `--ink`, `--ink-deep`, `--graphite`, `--pencil`, `--construction`, `--swash`, `--swash-strong`, `--amber`, `--amber-wash`, `--red`, `--mono`, `--script`, `--ease`, `--gutter`). Load JetBrains Mono (300/400/500) and Playfair Display (italic 700) through `next/font` and expose them as `--mono` and `--script`. Add `--swash-faint` for the row hover wash, which the prototype writes as a literal. Chart SVGs should take colour from these variables (or `currentColor`) rather than the hex literals the prototype inlines, so the tokens stay the single source.

**Key Characteristics:**
- Paper ground with a 40px construction dot grid; no cards, no fills behind content.
- One ink blue for the measured mark (prices, selection, the drawn line); everything else is graphite, pencil or construction.
- All text in JetBrains Mono with tabular numerals; the italic serif lives only in the wordmark.
- Square corners everywhere; circles only for bullets, status dots and annotation rings.
- Depth by line weight and dashing, never by shadow.
- Signature drawings: baseline ruler, annotation callout, dimension line, Baseline band chart.

## Colors

A drafting palette: one saturated ink on near-white paper, three greys with strictly separated jobs, and two state colours that never compete with the ink.

### Primary
- **Process Ink** (ink): the measured mark. Price figures at 24px and up, the ruler tick and dimension line, the route chart's price line and Travelpayouts dots, the active-nav bar, histogram outlines, radio/checkbox/range accents and the focus outline. At 4:1 on paper it is reserved for large figures and drawn strokes.
- **Deep Ink** (ink-deep): the text form of the ink, 6.3:1 on paper. Small accented text: callout percentages, verified tags, active nav labels, selected route names, emphasised figures inside descriptions, links, and primary marker buttons.
- **Ink Swash** (swash): a 12% ink wash for selected states (selected Deal row, selected table row, pressed segment, pressed icon button, focused input) and the Baseline ± MAD band.
- **Strong Swash** (swash-strong): 22% wash for the primary button hover, text selection, and the used portion of the Verification budget meter.
- **Faint Swash** (swash-faint): 5% wash for row hover only.

### Secondary
- **Provisional Amber** (amber): the colour of uncertainty. Unverified tags, the provisional-tier Baseline percentage, stale freshness dots, and "no data" coverage cells. Always paired with a dashed border so the state does not rely on hue alone.
- **Amber Wash** (amber-wash): the fill behind amber states: unverified tag ground, the provisional ruler band, and the diagonal hatch in missing-coverage cells.

### Tertiary
- **Failure Red** (red): failing asset checks, the "check failing" count, the delete action, and the hover on chip remove buttons. Used for genuine failure only; a fare drop is never red.

### Neutral
- **Drafting Paper** (paper): the page, the inspector, the sticky mobile nav, and the knock-out behind callout labels so they sit cleanly over rulers.
- **Graphite** (graphite): body text (8.6:1), headings, primary table header rule, input and button outlines, the median line on rulers and the Baseline line on charts, annotation rings and leader lines.
- **Pencil** (pencil): secondary text (5.3:1): sub-lines, labels, axis text, metadata, placeholders, nav items at rest, coordinate labels.
- **Construction** (construction): rules, dashed guides, ruler tracks, chart gridlines, the dot grid, row dividers, the nav and inspector separators, idle icon-button outlines.

### Named Rules
**The Construction Is Never Text Rule.** Construction grey (#d1d1d1) draws lines, guides and the dot grid only. Any glyph a person reads is graphite, pencil, deep ink, amber or red.

**The Two Inks Rule.** Process Ink is for marks and figures at 24px or larger; anything smaller that needs the ink voice uses Deep Ink. If it is text and under 24px, it is ink-deep.

**The Measured Mark Rule.** Ink marks the one thing being measured on a surface (the fare, the selection, the price line). Do not spend it on decoration, headings or chrome.

## Typography

**Display Font:** JetBrains Mono (with ui-monospace, SF Mono, Menlo, monospace)
**Body Font:** JetBrains Mono (same stack)
**Wordmark Font:** Playfair Display italic 700 (with Georgia, serif)

**Character:** A single engineering monospace does all the work, light (300) for big ink figures, regular for reading, medium (500) for names and headings, so numbers line up in every column. The italic serif is the hand of the draughtsman signing the sheet, and appears once.

### Hierarchy
- **Display** (300, 34px, 1.1, −0.02em): inspector data points: the selected price, % below Baseline, budget left, precision. Ink by default, amber when the Baseline is provisional. A pencil unit follows at 12px.
- **Figure** (300, 24px, 1.1, −0.02em): per-adult price at the right of each Deal row, in ink, with an 11px pencil "/adult".
- **Headline** (500, 22px, 1.2, −0.01em): page titles and the inspector's selected route (IATA → IATA).
- **Title** (500, 15px): route names in Deal rows; 13px medium for row titles in tables.
- **Body** (400, 13px, 1.6, tabular numerals): default text and inputs; tables run at 12px.
- **Body small** (400, 11px, 1.7): inspector descriptions, sub-lines, legends, axis and chart text, metadata.
- **Label** (400 or 500, 11px, uppercase, 0.1em): nav items (0.18em), field labels, table headers, inspector section labels, tags (500, 0.06em), segmented options and marker buttons (0.08 to 0.1em), section subheads (h2: 500, 0.12em, graphite).
- **Micro** (10px, 0.02 to 0.04em, pencil): coordinate labels and the nav foot coordinate only.
- **Wordmark** (Playfair Display italic 700, 19px, ink): "Flight Scanner" set vertically under the logo.

### Named Rules
**The One Hand Rule.** Playfair Display appears only in the wordmark. Every other glyph, including headings and figures, is JetBrains Mono.

**The Light Figure Rule.** Large numbers are light (300) and ink; names and headings are medium (500) and graphite. Weight, not size alone, separates measurement from label.

## Layout

The desktop shell is a three-column board inside a 32px gutter: an 80px rotated vertical nav, a fluid main canvas, and a 360px inspector rail, separated by 28px gaps and two rules (1.5px construction on the nav's right, 1px construction on the inspector's left). The shell is exactly one viewport tall; the canvas and the inspector scroll independently. The inspector stacks sections 40px apart, each a label, a figure or route, and a short description, closing with a dashed-ruled synthetic-data footnote pinned to the bottom.

Page headers sit on a dashed construction underline: title and an 11px lede on the left, controls (segmented filter, underlined selects, primary marker button) wrapping on the right. Section subheads open with 36px above and 14px below. Deal rows run on a four-column grid (route, dates, ruler, price; ruler column twice as wide), aligned under a scale header whose axis labels (€0, −50%, Baseline, +30%) sit at the same percentages as the rulers beneath. Rows are 18px × 12px padded and divided by 1px construction rules; table cells are 14px × 12px.

Coordinate labels sit fixed in the viewport corners in 10px pencil and carry live context: the current scan time and cadence at top right, host and tunnel at bottom left.

**Responsive.** At 1180px and below the shell tightens to a 72px nav, a 300px inspector, 22px gaps and a 24px gutter, and the Deal grid columns narrow. At 860px and below the shell becomes a single column: the nav turns into a sticky horizontal bar on paper with a 1.5px construction underline, horizontal labels and a 2px ink underbar for the active item; the wordmark becomes screen-reader-only and the logo drops to 34px; coordinate labels and the nav foot hide; the inspector follows the canvas under a 1.5px construction rule. Deal rows reflow to route + price on top, dates below, ruler full width; the selected row's ruler note moves beneath the ruler and its leader line is dropped. Data tables become stacked two-column records, each cell preceded by its header as an 11px uppercase pencil label, with the row title spanning the full width.

**The Ruled Not Boxed Rule.** Regions are separated by hairline rules and whitespace, never by panels or cards. If a new region seems to need a box, it needs a rule.

## Elevation & Depth

The system is completely flat: there is no box-shadow anywhere. Depth is stated by line language: solid 1.5px graphite for the strongest edges (input underlines, button outlines, table header rule, histogram baseline), 1px construction for dividers, dashed construction for guides and headers, dashed graphite or ink for measured bounds, and a 12 to 22% ink wash for selection. Layering is limited to the sticky mobile nav and callout labels, both of which simply knock out on paper.

**The Line Weight Rule.** Hierarchy comes from stroke weight and dash, never from shadow or blur. Heavier and solid means structural; lighter and dashed means a guide or an estimate.

## Shapes

Every corner is square (0px): buttons, inputs, tags, chips, segmented controls, matrix cells, histogram bars. Circles are reserved for small instrument marks: the 8px circle bullet before inspector labels, the 7px freshness dot, tier-ladder dots, the 8px tick head on rulers, the dashed annotation ring and the logo's construction circle.

Dashing is a semantic shape, not a texture. A dashed outline means estimated, unverified, excluded, paused or missing: unverified tags, excluded chips, paused tags, the Baseline band edges, the return-overflow segment of the trip window, missed bars in the backtest histogram, and missing-coverage cells (dashed amber with a 45° amber hatch).

Icons are 14px (16px in icon buttons, 11px inside tags and chips) line drawings on a 16px grid with a 1.5px round-capped stroke in the current colour, matching the hand of the drawings.

**The Dash Means Doubt Rule.** A solid line is observed or confirmed; a dashed line is inferred, provisional or absent. Never dash something for decoration.

## Components

### Buttons
Outlined marker strokes on bare paper.
- **Shape:** square, 1.5px outline, 11px uppercase label at 0.1em, 8px × 18px.
- **Default:** graphite outline and text.
- **Primary:** ink outline with deep-ink text; the full-width Book button in the inspector uses 11px vertical padding, centred, with a trailing external-link icon.
- **Hover:** outline goes ink, text deep ink, an ink swash fills it (strong swash on primary), and the button tilts −1° (0.2s ease).
- **Danger:** no outline, red text, tight padding; hover underlines instead of tilting.
- **Icon button:** 36px square, construction outline at rest, ink outline and −2° tilt on hover, swash fill when pressed (used for the 👍/👎 rating pair as drawn thumb icons).
- **Focus:** 1.5px ink outline offset 3px on every focusable element.

### Segmented filter
A 1.5px graphite frame holding uppercase 11px options split by 1px construction rules; the pressed option takes the swash and deep-ink text.

### Tags
11px medium uppercase at 0.06em, 2px × 7px, 1px outline in the current colour, optional 11px leading icon.
- **Verified / Active / Pass:** deep ink outline and text, check icon.
- **Unverified:** amber text, dashed amber outline, amber wash, dashed-circle icon.
- **Plain (e.g. 2 separate tickets):** pencil text, construction outline.
- **Drop:** deep ink on swash, no outline.
- **Off / Paused:** pencil text, dashed pencil outline.
- **Fail:** red text and outline.

### Chips (Place picker)
Graphite 1px outline, name in graphite, kind (airport, region, country) in 11px uppercase pencil, and an 18px remove button that turns red on hover. Exclusions are dashed and pencil, carry a leading minus icon, and strike through the name.

### Inputs / Fields
- **Style:** no box: transparent ground with a single 1.5px graphite underline, 13px text, 6px × 2px padding, square. Selects add a small graphite chevron at the right.
- **Label:** 11px uppercase pencil at 0.1em, 6px above the field.
- **Hover / Focus:** underline turns ink; focus adds the swash behind the field instead of an outline.
- **Stepper:** minus / value / plus on the same underline. Range, radio and checkbox use the native control with the ink accent.

### Navigation
Rotated vertical labels (read bottom to top) in 11px uppercase pencil at 0.18em, 34px apart, under the hand-drawn logo and vertical wordmark. Hover and the current page turn deep ink; the current page also gets a 2px × 40px ink bar to its right. A 10px pencil coordinate (the home airport's latitude and longitude) sits at the foot. Mobile behaviour is under Layout.

### Inspector sections
Each section opens with a label: 11px uppercase graphite preceded by an 8px ink-outlined circle bullet, which names the value beneath it. Below it, a Display figure or Headline route, then 11px graphite description text where emphasised values switch to deep ink (never italic). Itinerary legs run as a two-column list of uppercase direction and medium time with a pencil sub-line. Data tables use pencil uppercase headers over a 1.5px graphite rule, 1px construction row dividers, right-aligned numerals, and swash for the selected row.

### Baseline ruler (signature)
The per-Deal drawing that replaces a discount badge. On a 54px-tall strip, a construction track with 14 ticks spans €0 to 140% of the Baseline. The Baseline ± MAD sits as a 30px swash band with dashed ink edges (amber wash and dashed amber when the tier is provisional); the median is a 1.5px dashed graphite line. The fare is a 2px ink tick with an 8px ink dot at its foot. A 1px ink dimension line with 7px end serifs spans from the tick to the median and draws in from the right (0.7s, the house ease) when the view opens; above its midpoint a deep-ink 11px medium callout states the gap (e.g. −45%) on a paper knock-out.

### Annotation callout (signature)
The leader-line note used on the selected ruler and on the route chart. A dashed graphite ring (22px on the ruler, 26px on the chart) circles the mark; a 1px graphite leader line runs up-left at an angle to a right-aligned note whose first line is 11px medium uppercase deep ink (the price and state) and whose second line is pencil detail (verification time or cache age). On rulers the note sits on a pale ink-tinted knock-out.

### Trip-pattern dimension line (signature)
The resolved window in the Watch editor, drawn like an architectural dimension. A 1px ink dimension line with end serifs spans the departure window, labelled above in 11px medium deep ink ("30 days · depart"); below it, a 16px swash bar bounded by 1.5px ink edges marks the window on a construction axis, a dashed ink step shows how far returns can run past it, and pencil date labels mark start, end and latest return.

### Route chart (signature)
A 300px SVG on the same conventions: dashed construction gridlines with pencil € labels at the left; a pale ink Baseline band bounded by dashed ink lines at ± MAD; a dashed graphite Baseline line labelled in medium graphite at the right margin ("BASELINE €214", "± MAD €18"), moving inside the plot as one label on narrow widths; the daily minimum as a 1.5px ink line that draws once on open (1.1s); Travelpayouts points as 2px paper-filled ink circles and Price insight points as 6px paper-filled graphite squares; the latest Deal marked with the annotation callout; a solid graphite x-axis with 4px ticks. A pencil legend of drawn swatches follows. Backtest histograms and the budget meter reuse the same grammar: ink-outlined swash bars rising from a 1.5px graphite baseline (dashed graphite and unfilled for misses), and a ticked graphite scale filled in strong swash up to a dashed ink "today" marker.

### State indicators
Freshness is a 7px dot: solid ink when fresh, amber ring when stale, dashed pencil ring when disabled, always followed by its text. Coverage cells are 1px construction boxes whose ink tint scales with the percentage (up to 28%), with missing cells shown as dashed, hatched amber "no data". Empty states are centred pencil text with a medium graphite first line over a dashed construction rule.

## Do's and Don'ts

### Do:
- **Do** draw every price against its Baseline: ruler, band, tick, dimension line and a callout with the % below.
- **Do** use ink (#0076ff) only for figures 24px and larger and for drawn marks; set smaller ink-voiced text in ink-deep (#0058c4).
- **Do** mark uncertainty with dashing plus amber (unverified, provisional, missing coverage), and always with a text label alongside.
- **Do** keep corners square and separate regions with 1px or 1.5px rules, not containers.
- **Do** put real data in the coordinate labels (scan time, cadence, host, tunnel) and keep standard cursors.
- **Do** honour reduced motion: the ink draw-in, histogram rise and hover tilts all switch off under `prefers-reduced-motion`.
- **Do** label synthetic or placeholder data as such, in the pencil footnote style.

### Don't:
- **Don't** use construction grey (#d1d1d1) for any readable text.
- **Don't** add box-shadows, rounded cards, filled panels or decorative colour gradients; gradients exist only to draw the dot grid, ruler and scale ticks, and the missing-data hatch.
- **Don't** show a fare drop as a red badge; red is for failures only.
- **Don't** use Playfair Display anywhere but the wordmark.
- **Don't** replace the hand-drawn "fs" logo with a typeset mark or a generic plane glyph.
- **Don't** use custom cursors or decorative, non-data coordinate labels.
- **Don't** dash a line unless it means estimated, unverified, excluded or missing.
