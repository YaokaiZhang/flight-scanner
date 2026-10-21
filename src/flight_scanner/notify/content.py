"""What an Alert says, as text: one rendering shared by every channel.

`subject(alert)` is the one-line summary (email subject, Telegram headline); `lines(alert)` the
body, one fact per line, leaving out what isn't known (no Baseline yet, airline unknown, ...);
`html_lines` the same with the headline and booking link marked up (escaped, Telegram-safe HTML).
A Digest (`digest_subject`, `digest_text`, `digest_html`) is its Deals' Alerts, numbered, in one
message.
"""

from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from flight_scanner.notify.base import AlertMessage, DigestMessage


def booking_link(origin: str, destination: str, outbound: date, inbound: date | None) -> str:
    """A Google Flights search for exactly this trip; used when the source gave no deep link."""
    q = f"Flights from {origin} to {destination} on {outbound.isoformat()}"
    q += f" returning {inbound.isoformat()}" if inbound else " one way"
    return f"https://www.google.com/travel/flights?q={quote(q)}&curr=EUR"


def eur(amount: float) -> str:
    return f"€{amount:,.0f}" if amount == int(amount) else f"€{amount:,.2f}"


def _day(d: date) -> str:
    return d.strftime("%a %-d %b %Y")


def _duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _stops(n: int) -> str:
    return "direct" if n == 0 else f"{n} stop" + ("s" if n > 1 else "")


def _status(a: AlertMessage) -> str:
    return "Verified" if a.verification == "verified" else "Unverified"


def subject(a: AlertMessage) -> str:
    return (
        f"{a.origin}→{a.destination} {a.outbound_date.strftime('%-d %b')}"
        f"{' – ' + a.return_date.strftime('%-d %b') if a.return_date else ''}: "
        f"{eur(a.price_per_adult_eur)}/adult · {_status(a)}"
    )


def lines(a: AlertMessage) -> list[str]:
    out = [a.watch_name]
    if a.return_date:
        nights = (a.return_date - a.outbound_date).days
        out.append(
            f"{a.origin} → {a.destination} · {_day(a.outbound_date)} → {_day(a.return_date)}"
            f" · {nights} night{'s' if nights != 1 else ''}"
        )
    else:
        out.append(f"{a.origin} → {a.destination} · {_day(a.outbound_date)} · one way")
    price = f"{eur(a.price_per_adult_eur)} per adult"
    if a.adults > 1:
        price += f" · {eur(a.price_total_eur)} total for {a.adults} adults"
    out.append(price)
    if a.pct_below_baseline is not None:
        out.append(
            f"{a.pct_below_baseline:g}% below Baseline {eur(a.baseline_per_adult_eur)}"
            + (f" ({a.baseline_tier})" if a.baseline_tier else "")
        )
    flight = [
        p
        for p in (
            a.airlines,
            _stops(a.stops) if a.stops is not None else None,
            _duration(a.travel_minutes) if a.travel_minutes is not None else None,
        )
        if p
    ]
    if flight:
        out.append(" · ".join(flight))
    if a.separate_tickets:
        out.append("2 separate tickets")
    if a.deal_context:
        out.append(f"Why cheap? {a.deal_context}")
    if a.verification == "verified":
        out.append("Verified: checked live.")
    else:
        out.append(f"Unverified: cached price from {a.source}, not checked live.")
    return out


def text(a: AlertMessage) -> str:
    return "\n".join([*lines(a), f"Book: {a.booking_url}"])


def html_lines(a: AlertMessage) -> list[str]:
    body = [escape(line) for line in lines(a)]
    body[0] = f"<b>{escape(subject(a))}</b>\n{body[0]}"
    body.append(f'<a href="{escape(a.booking_url, quote=True)}">Book this trip</a>')
    return body


def digest_subject(d: DigestMessage) -> str:
    n = len(d.deals)
    return f"Daily Digest · {d.watch_name}: {n} Deal{'s' if n != 1 else ''}"


def digest_text(d: DigestMessage) -> str:
    parts = [digest_subject(d)]
    parts += [f"{i}. {subject(a)}\n{text(a)}" for i, a in enumerate(d.deals, 1)]
    return "\n\n".join(parts)


def digest_html(d: DigestMessage) -> str:
    """Compact (one headline + link per Deal) to stay within a Telegram message."""
    parts = [f"<b>{escape(digest_subject(d))}</b>"]
    parts += [
        f"{i}. {escape(subject(a))}\n"
        f'<a href="{escape(a.booking_url, quote=True)}">Book this trip</a>'
        for i, a in enumerate(d.deals, 1)
    ]
    return "\n\n".join(parts)
