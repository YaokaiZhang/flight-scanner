"""Telegram channel: one bot message per Alert, with 👍/👎 buttons and a Book button.

A Digest is one message listing its Deals (numbered) with one row of buttons per Deal: n 👍, n 👎.

Settings (environment): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (the owner's chat with the bot),
TELEGRAM_API_URL (default https://api.telegram.org; tests point it at a fake).

Button callbacks carry `rate:<alert id>:<up|down>`. Nothing here is public, so there is no
webhook: `collect_feedback` drains pending callbacks with a non-blocking `getUpdates` (the
`telegram_feedback` Dagster sensor calls it every 30 s), records each tap from the owner's chat
against its Alert, and acknowledges every tap. The update offset lives in `app.notifier_state`.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from flight_scanner import feedback
from flight_scanner.notify import content
from flight_scanner.notify.base import AlertMessage, DigestMessage

log = logging.getLogger(__name__)

_OFFSET_KEY = "telegram.update_offset"
_THANKS = {"up": "Rated 👍", "down": "Rated 👎"}


class TelegramError(Exception):
    pass


@dataclass(frozen=True)
class TelegramSettings:
    token: str
    chat_id: str
    api_url: str = "https://api.telegram.org"

    @classmethod
    def from_env(cls, env: dict[str, str]) -> TelegramSettings:
        def need(key: str) -> str:
            value = env.get(key, "").strip()
            if not value:
                raise ValueError(f"the telegram notifier needs {key}")
            return value

        return cls(
            token=need("TELEGRAM_BOT_TOKEN"),
            chat_id=need("TELEGRAM_CHAT_ID"),
            api_url=(env.get("TELEGRAM_API_URL", "").strip() or cls.api_url).rstrip("/"),
        )


def _rating_buttons(alert: AlertMessage, label: str) -> list[dict]:
    if alert.alert_id is None:
        return []
    return [
        {"text": f"{label}👍", "callback_data": f"rate:{alert.alert_id}:up"},
        {"text": f"{label}👎", "callback_data": f"rate:{alert.alert_id}:down"},
    ]


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, settings: TelegramSettings, timeout: float = 30.0):
        self.settings = settings
        self.timeout = timeout

    def _call(self, method: str, body: dict) -> object:
        req = urllib.request.Request(
            f"{self.settings.api_url}/bot{self.settings.token}/{method}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                doc = json.loads(res.read())
        except urllib.error.HTTPError as e:
            try:
                doc = json.loads(e.read())
            except ValueError:
                doc = {"description": f"HTTP {e.code}"}
        except urllib.error.URLError as e:
            # Never let the token (it is in the URL) reach logs or exceptions.
            raise TelegramError(f"{method}: {e.reason}") from None
        if not doc.get("ok"):
            raise TelegramError(f"{method}: {doc.get('description', 'not ok')}")
        return doc["result"]

    def send(self, alert: AlertMessage) -> None:
        buttons = _rating_buttons(alert, "")
        buttons.append({"text": "Book", "url": alert.booking_url})
        self._send_html("\n".join(content.html_lines(alert)), [buttons])

    def send_digest(self, digest: DigestMessage) -> None:
        rows = [_rating_buttons(a, f"{i} ") for i, a in enumerate(digest.deals, 1)]
        self._send_html(content.digest_html(digest), [r for r in rows if r])

    def _send_html(self, html: str, keyboard: list[list[dict]]) -> None:
        body: dict = {
            "chat_id": self.settings.chat_id,
            "text": html,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if keyboard:
            body["reply_markup"] = {"inline_keyboard": keyboard}
        self._call("sendMessage", body)

    def collect_feedback(self, conn: psycopg.Connection, now: datetime) -> int:
        """Record pending 👍/👎 taps; returns how many were recorded."""
        row = conn.execute(
            "SELECT value FROM app.notifier_state WHERE name = %s", (_OFFSET_KEY,)
        ).fetchone()
        offset = int(row["value"]) if row else 0
        updates = self._call(
            "getUpdates",
            {"offset": offset, "timeout": 0, "allowed_updates": ["callback_query"]},
        )
        recorded = 0
        for update in updates:  # type: ignore[union-attr]
            cb = update.get("callback_query")
            if cb:
                rating = self._rating(cb)
                ok = rating is not None and feedback.rate_alert(
                    conn, rating[0], rating[1], "telegram", now
                )
                recorded += ok
                try:
                    self._call(
                        "answerCallbackQuery",
                        {"callback_query_id": cb["id"], "text": _THANKS[rating[1]] if ok else ""},
                    )
                except TelegramError as e:  # too old to answer; the rating still counts
                    log.info("answerCallbackQuery failed: %s", e)
            offset = max(offset, int(update["update_id"]) + 1)
            conn.execute(
                "INSERT INTO app.notifier_state (name, value) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (_OFFSET_KEY, Jsonb(offset)),
            )
        return recorded

    def _rating(self, cb: dict) -> tuple[int, feedback.Rating] | None:
        """(alert id, rating) for a tap from the owner's chat on one of our buttons, else None."""
        chat = (cb.get("message") or {}).get("chat") or {}
        if str(chat.get("id")) != self.settings.chat_id:
            return None
        parts = str(cb.get("data", "")).split(":")
        if len(parts) != 3 or parts[0] != "rate" or parts[2] not in ("up", "down"):
            return None
        try:
            return int(parts[1]), parts[2]  # type: ignore[return-value]
        except ValueError:
            return None
