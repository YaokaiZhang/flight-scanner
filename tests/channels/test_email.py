"""Email channel: configured from the environment, delivered over SMTP to a local test server."""

import socket
from dataclasses import replace
from email import message_from_bytes, policy

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from flight_scanner.config import Settings
from flight_scanner.notify.base import DigestMessage
from flight_scanner.notify.registry import build_notifiers


class Inbox:
    def __init__(self):
        self.messages = []
        self.logins = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append((envelope.mail_from, envelope.rcpt_tos, envelope.content))
        return "250 OK"

    def authenticate(self, server, session, envelope, mechanism, auth_data):
        assert isinstance(auth_data, LoginPassword)
        self.logins.append((auth_data.login.decode(), auth_data.password.decode()))
        # handled=False: aiosmtpd itself answers a failure with 535 (handled=True, the default,
        # sends nothing and the client hangs until its 30 s timeout)
        return AuthResult(success=auth_data.password == b"test-secret", handled=False)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp():
    inbox = Inbox()
    controller = Controller(
        inbox,
        hostname="127.0.0.1",
        port=free_port(),
        authenticator=inbox.authenticate,
        auth_require_tls=False,
    )
    controller.start()
    try:
        yield inbox, controller.port
    finally:
        controller.stop()


def email_env(port: int, **extra) -> dict:
    return {
        "FS_NOTIFIERS": "email",
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": str(port),
        "SMTP_SECURITY": "none",
        "SMTP_USER": "scanner",
        "SMTP_PASSWORD": "test-secret",
        "ALERT_EMAIL_FROM": "scanner@example.test",
        "ALERT_EMAIL_TO": "owner@example.test",
        **extra,
    }


def test_email_alert_is_sent_over_smtp_with_full_deal_details(smtp, round_trip_alert):
    inbox, port = smtp
    [notifier] = build_notifiers(Settings.from_env(email_env(port)))
    assert notifier.channel == "email"

    notifier.send(round_trip_alert)

    assert inbox.logins == [("scanner", "test-secret")]
    [(sender, recipients, raw)] = inbox.messages
    assert (sender, recipients) == ("scanner@example.test", ["owner@example.test"])
    msg = message_from_bytes(raw, policy=policy.default)
    assert msg["Subject"] == "Helsinki Vantaa → Hurghada 14 Nov – 19 Nov: €118/adult · Verified"
    text = msg.get_body(("plain",)).get_content()
    assert text.splitlines() == [
        "Sun in November",
        "Helsinki Vantaa Airport (HEL), Finland → Hurghada International Airport (HRG), Egypt",
        "Sat 14 Nov 2026 → Thu 19 Nov 2026 · 5 nights",
        "€118 per adult · €236 total for 2 adults",
        "44.9% below Baseline €214 (route)",
        "airBaltic, Ryanair · 1 stop · 15 h 25 min",
        "2 separate tickets",
        "Verified: checked live.",
        "Book: https://example.test/book?trip=HEL-HRG&a=1&b=2",
    ]
    html = msg.get_body(("html",)).get_content()
    assert 'href="https://example.test/book?trip=HEL-HRG&amp;a=1&amp;b=2"' in html


def test_email_delivery_failure_raises(smtp, round_trip_alert):
    _, port = smtp
    [notifier] = build_notifiers(Settings.from_env(email_env(port, SMTP_PASSWORD="wrong-password")))
    with pytest.raises(Exception):  # noqa: B017 - any failure must surface to the pipeline
        notifier.send(round_trip_alert)


def test_email_needs_its_settings():
    with pytest.raises(ValueError, match="SMTP_HOST"):
        build_notifiers(Settings.from_env({"FS_NOTIFIERS": "email"}))


def two_deal_digest(alert) -> DigestMessage:
    other = replace(alert, deal_id=8, destination="LPA", alert_id=42)
    return DigestMessage(watch_id=3, watch_name="Sun in November", deals=(alert, other))


def test_an_email_digest_is_one_message_listing_every_deal(smtp, round_trip_alert):
    inbox, port = smtp
    [notifier] = build_notifiers(Settings.from_env(email_env(port)))

    notifier.send_digest(two_deal_digest(round_trip_alert))

    [(_, _, raw)] = inbox.messages
    msg = message_from_bytes(raw, policy=policy.default)
    assert msg["Subject"] == "Daily Digest · Sun in November: 2 Deals"
    text = msg.get_body(("plain",)).get_content()
    assert (
        "1. Helsinki Vantaa → Hurghada 14 Nov" in text
        and "2. Helsinki Vantaa → Gran Canaria 14 Nov" in text
    )
    assert text.count("Book: https://example.test/book") == 2
