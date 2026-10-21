-- Change-only Round-trip-price history: one row per price change per source, route and dates.
{{ change_only_history(
    ref('stg_round_trip_prices'),
    ['source', 'origin', 'destination', 'departure_date', 'return_date']
) }}
