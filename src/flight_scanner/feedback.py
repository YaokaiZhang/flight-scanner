"""👍/👎 on Deals: from Telegram buttons (tied to the Alert that carried them) or the Deals feed.

Feedback is append-only; a Deal's current rating is its latest row (a null rating clears it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import psycopg

Rating = Literal["up", "down"]
Via = Literal["telegram", "web"]

# Latest feedback per Deal, for joining into Deal reads: `LEFT JOIN LATERAL (<this>) f ON true`.
LATEST_FOR_DEAL = """SELECT fb.rating AS feedback_rating, fb.via AS feedback_via
                     FROM app.deal_feedback fb WHERE fb.deal_id = d.id
                     ORDER BY fb.created_at DESC, fb.id DESC LIMIT 1"""


def rate_deal(
    conn: psycopg.Connection, deal_id: int, rating: Rating | None, via: Via, now: datetime
) -> bool:
    """Record a rating for a Deal; False when the Deal doesn't exist."""
    cur = conn.execute(
        """INSERT INTO app.deal_feedback (deal_id, rating, via, created_at)
           SELECT id, %s, %s, %s FROM app.deals WHERE id = %s""",
        (rating, via, now, deal_id),
    )
    return cur.rowcount == 1


def rate_alert(
    conn: psycopg.Connection, alert_id: int, rating: Rating, via: Via, now: datetime
) -> bool:
    """Record a rating given on an Alert (for its Deal); False when the Alert doesn't exist."""
    cur = conn.execute(
        """INSERT INTO app.deal_feedback (deal_id, alert_id, rating, via, created_at)
           SELECT deal_id, id, %s, %s, %s FROM app.alerts WHERE id = %s""",
        (rating, via, now, alert_id),
    )
    return cur.rowcount == 1
