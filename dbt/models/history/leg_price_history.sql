-- Change-only Leg-price history: one row per price change per source, route and departure date.
{{ change_only_history(ref('stg_leg_prices'), ['source', 'origin', 'destination', 'departure_date']) }}
