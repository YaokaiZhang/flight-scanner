# Round trips are composed from Leg prices, plus Round-trip prices

Pricing every exact round-trip itinerary for a wide Watch (HEL → ~150 airports × ~60 dates × several stay lengths) needs ~18k live queries per scan, which no free source allows. Because the owner accepts two separately booked one-way tickets as a Round trip, we instead collect one-way **Leg prices** per (route, day) — most sources return a whole month of daily prices per call, so a full scan is ~600 calls — and compose round trips by pairing outbound and return Leg prices in SQL. Single-ticket returns can undercut two one-ways (common with full-service carriers such as Finnair), so we also store **Round-trip prices** where a source provides them, and a trip's price is the cheaper of the pairing and the single ticket. Verification of Candidates is always done in round-trip mode.

## Consequences

- A residual blind spot remains: a single-ticket return fare on dates and a route no source covered. The data-health page surfaces coverage gaps instead of hiding them.
- Self-transfer within one direction is deliberately excluded; separate tickets are only allowed between outbound and return.
