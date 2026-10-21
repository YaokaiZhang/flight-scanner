"""Telegram channel: configured from the environment, delivered to a fake Bot API endpoint."""

from dataclasses import replace

import pytest

from flight_scanner.config import Settings
from flight_scanner.notify.base import DigestMessage
from flight_scanner.notify.registry import build_notifiers
from flight_scanner.testing.fake_telegram import FakeTelegram


@pytest.fixture
def telegram():
    with FakeTelegram() as tg:
        yield tg


def telegram_env(tg: FakeTelegram) -> dict:
    return {
        "FS_NOTIFIERS": "telegram",
        "TELEGRAM_BOT_TOKEN": tg.token,
        "TELEGRAM_CHAT_ID": str(tg.chat_id),
        "TELEGRAM_API_URL": tg.url,
    }


def test_telegram_alert_carries_deal_details_a_booking_link_and_rating_buttons(
    telegram, round_trip_alert
):
    [notifier] = build_notifiers(Settings.from_env(telegram_env(telegram)))
    assert notifier.channel == "telegram"

    notifier.send(round_trip_alert)

    [sent] = telegram.calls_to("sendMessage")
    assert sent["chat_id"] == str(telegram.chat_id)
    assert sent["parse_mode"] == "HTML"
    assert sent["text"].splitlines() == [
        "<b>HEL→HRG 14 Nov – 19 Nov: €118/adult · Verified</b>",
        "Sun in November",
        "HEL → HRG · Sat 14 Nov 2026 → Thu 19 Nov 2026 · 5 nights",
        "€118 per adult · €236 total for 2 adults",
        "44.9% below Baseline €214 (route)",
        "airBaltic, Ryanair · 1 stop · 15 h 25 min",
        "2 separate tickets",
        "Verified: checked live.",
        '<a href="https://example.test/book?trip=HEL-HRG&amp;a=1&amp;b=2">Book this trip</a>',
    ]
    assert sent["reply_markup"] == {
        "inline_keyboard": [
            [
                {"text": "👍", "callback_data": "rate:41:up"},
                {"text": "👎", "callback_data": "rate:41:down"},
                {"text": "Book", "url": "https://example.test/book?trip=HEL-HRG&a=1&b=2"},
            ]
        ]
    }


def test_telegram_delivery_failure_raises(telegram, round_trip_alert):
    [notifier] = build_notifiers(Settings.from_env(telegram_env(telegram)))
    telegram.fail_next("sendMessage")

    with pytest.raises(Exception, match="Bad Request"):
        notifier.send(round_trip_alert)


def test_telegram_needs_its_settings():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        build_notifiers(Settings.from_env({"FS_NOTIFIERS": "telegram"}))


def two_deal_digest(alert) -> DigestMessage:
    other = replace(alert, deal_id=8, destination="LPA", alert_id=42)
    return DigestMessage(watch_id=3, watch_name="Sun in November", deals=(alert, other))


def test_a_telegram_digest_is_one_message_with_rating_buttons_per_deal(
    telegram,
    round_trip_alert,
):
    [notifier] = build_notifiers(Settings.from_env(telegram_env(telegram)))

    notifier.send_digest(two_deal_digest(round_trip_alert))

    [sent] = telegram.calls_to("sendMessage")
    assert sent["text"].startswith("<b>Daily Digest · Sun in November: 2 Deals</b>")
    assert "1. HEL→HRG 14 Nov" in sent["text"] and "2. HEL→LPA 14 Nov" in sent["text"]
    assert sent["reply_markup"]["inline_keyboard"] == [
        [
            {"text": "1 👍", "callback_data": "rate:41:up"},
            {"text": "1 👎", "callback_data": "rate:41:down"},
        ],
        [
            {"text": "2 👍", "callback_data": "rate:42:up"},
            {"text": "2 👎", "callback_data": "rate:42:down"},
        ],
    ]
