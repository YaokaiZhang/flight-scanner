# Flight Scanner

A personal tool that continuously watches flight prices for the places its owner cares about and alerts them when a fare is significantly below what that trip normally costs.

## Language

### What the owner wants

**Watch**:
A saved search: origins, destinations, a Trip pattern, passenger count and an optional price threshold. The unit the owner creates and manages.
_Avoid_: Search, subscription, alert rule

**Trip pattern**:
When and how long the owner wants to travel, expressed as a departure window plus a range of stay nights (absent for one-way). Only the departure must fall in the window; the return may fall outside it. A window may be fixed dates or rolling (relative to today, sliding daily). A fixed-date trip is a zero-width window with min = max nights.
_Avoid_: Date range, flexible dates

**Stay nights**:
Trip length counted in nights between outbound departure date and return date (22 Nov → 25 Nov = 3).
_Avoid_: Days, duration

**Place**:
Something a Watch can name as origin or destination: an airport, city, country or Region. Every Place resolves to a set of airports.
_Avoid_: Location, destination (as a noun for the thing itself)

**Region**:
A named group of countries from a reference dataset (continents such as Europe, plus named groups such as Nordics or Schengen). Territories belong to their sovereign country's region, so the Canary Islands are in Europe.
_Avoid_: Area, zone

**Exclusion**:
A Place removed from a Watch's resolved destination (or origin) set, e.g. Europe excluding Sweden.
_Avoid_: Filter, blacklist

**Price threshold**:
An optional absolute ceiling on a Watch, applied in addition to the Baseline test.
_Avoid_: Budget, limit

### What we observe and judge

**Fare observation**:
One price seen for one itinerary at one moment from one source.
_Avoid_: Quote, result, price point

**Leg price**:
The cheapest one-way fare for one origin airport, destination airport and departure date, as seen from one source at one moment. Round trips are composed by pairing two Leg prices.
_Avoid_: One-way fare, segment price

**Round-trip price**:
A Fare observation for a single ticket covering both outbound and return dates; kept alongside Leg prices because single-ticket returns can undercut two one-ways.
_Avoid_: Return fare

**Round trip**:
An outbound and a return itinerary between the same areas; may be a single ticket or two independently booked one-way tickets, possibly on different airlines.
_Avoid_: Return ticket (implies a single booking)

**Self-transfer**:
Connecting between separately booked tickets within one direction of travel (e.g. Finnair HEL→BER then Ryanair BER→HRG). Not considered; separate tickets are only allowed between the outbound and the return.

**Baseline**:
The normal per-adult price for a comparable trip, learned from our own Fare observations over time.
_Avoid_: Average price, regular price

**Candidate**:
A trip whose observed (possibly cached) price passes the Deal test but has not yet been confirmed live.
_Avoid_: Potential deal, lead

**Verification**:
A live price check of a Candidate for the Watch's passenger count, done in round-trip mode. A Candidate that passes becomes a Verified Deal; when the live-check budget is exhausted it is alerted as an Unverified Deal.
_Avoid_: Confirmation, recheck

**Deal**:
A trip at least a set percentage below its Baseline and, if the Watch has one, under its Price threshold. Either Verified or Unverified.
_Avoid_: Bargain, cheap flight, hit

**Deal context**:
A short explanation attached to a Deal of why it might be cheap (sale, new route, off-season), gathered by web research.
_Avoid_: Reason, enrichment

### Telling the owner

**Alert**:
A notification to the owner about a Deal, sent once per Watch, route and dates, and again only if the price drops further by a set margin or the fare reappears after disappearing for a day.
_Avoid_: Notification (the delivery mechanism), message

**Digest**:
An optional per-Watch daily summary of Deals in place of immediate Alerts.
