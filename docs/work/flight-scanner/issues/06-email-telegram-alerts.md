# 06: Email and Telegram Alerts with feedback

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Alerts reach the owner for real. Email and Telegram notifiers implement the notifier interface; each Alert carries full Deal details and a booking link; the owner chooses channels per Watch and rates Alerts 👍/👎 from Telegram or the Deals feed.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Email (SMTP) and Telegram notifiers implement the notifier interface; configuration from environment.
- [ ] Alert content: route, dates, airlines, stops, total travel time, total and per-adult price, Baseline and % below (when present), Verified/Unverified, "2 separate tickets" when applicable, booking link.
- [ ] Per-Watch channel choice: email, Telegram or both.
- [ ] Telegram Alerts carry 👍/👎 buttons whose callbacks are recorded against the Alert.
- [ ] The Deals feed allows 👍/👎 and filters by Watch and status.
- [ ] Seam-1 test asserts recorded Alert content for a Deal; seam-2 tests cover feedback via the API.
