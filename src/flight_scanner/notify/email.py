"""Email channel: one plain-text + HTML message per Alert (or per Digest) over SMTP.

Settings (environment): SMTP_HOST, SMTP_PORT (587), SMTP_SECURITY (starttls | ssl | none;
default starttls), SMTP_USER / SMTP_PASSWORD (optional; login when set), ALERT_EMAIL_FROM
(default SMTP_USER), ALERT_EMAIL_TO (comma-separated).
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from typing import Literal

from flight_scanner.notify import content
from flight_scanner.notify.base import AlertMessage, DigestMessage


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    security: Literal["starttls", "ssl", "none"]
    user: str | None
    password: str | None
    sender: str
    recipients: tuple[str, ...]

    @classmethod
    def from_env(cls, env: dict[str, str]) -> SmtpSettings:
        def need(key: str) -> str:
            value = env.get(key, "").strip()
            if not value:
                raise ValueError(f"the email notifier needs {key}")
            return value

        host = need("SMTP_HOST")
        security = env.get("SMTP_SECURITY", "").strip() or "starttls"
        if security not in ("starttls", "ssl", "none"):
            raise ValueError(f"SMTP_SECURITY must be starttls, ssl or none, not {security!r}")
        user = env.get("SMTP_USER", "").strip() or None
        sender = env.get("ALERT_EMAIL_FROM", "").strip() or user
        if not sender:
            raise ValueError("the email notifier needs ALERT_EMAIL_FROM (or SMTP_USER)")
        recipients = tuple(r.strip() for r in need("ALERT_EMAIL_TO").split(",") if r.strip())
        default_port = {"ssl": "465", "starttls": "587", "none": "25"}[security]
        return cls(
            host=host,
            port=int(env.get("SMTP_PORT", "").strip() or default_port),
            security=security,  # type: ignore[arg-type]
            user=user,
            password=env.get("SMTP_PASSWORD") or None,
            sender=sender,
            recipients=recipients,
        )


def compose(alert: AlertMessage, sender: str, recipients: tuple[str, ...]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = content.subject(alert)
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(content.text(alert))
    html = "<br>\n".join(content.html_lines(alert)).replace("\n", "<br>\n")
    msg.add_alternative(f"<!doctype html><html><body><p>{html}</p></body></html>", subtype="html")
    return msg


def compose_digest(digest: DigestMessage, sender: str, recipients: tuple[str, ...]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = content.digest_subject(digest)
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(content.digest_text(digest))
    deals = "".join(
        f"<p>{i}. " + "<br>\n".join(content.html_lines(a)).replace("\n", "<br>\n") + "</p>\n"
        for i, a in enumerate(digest.deals, 1)
    )
    title = escape(content.digest_subject(digest))
    msg.add_alternative(
        f"<!doctype html><html><body><p><b>{title}</b></p>\n{deals}</body></html>", subtype="html"
    )
    return msg


class EmailNotifier:
    channel = "email"

    def __init__(self, settings: SmtpSettings, timeout: float = 30.0):
        self.settings = settings
        self.timeout = timeout

    def send(self, alert: AlertMessage) -> None:
        self._deliver(compose(alert, self.settings.sender, self.settings.recipients))

    def send_digest(self, digest: DigestMessage) -> None:
        self._deliver(compose_digest(digest, self.settings.sender, self.settings.recipients))

    def send_ops(self, text: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = text.split(".")[0]
        msg["From"] = self.settings.sender
        msg["To"] = ", ".join(self.settings.recipients)
        msg.set_content(text)
        self._deliver(msg)

    def _deliver(self, msg: EmailMessage) -> None:
        s = self.settings
        if s.security == "ssl":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                s.host, s.port, timeout=self.timeout, context=ssl.create_default_context()
            )
        else:
            smtp = smtplib.SMTP(s.host, s.port, timeout=self.timeout)
        with smtp:
            if s.security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if s.user and s.password:
                smtp.login(s.user, s.password)
            smtp.send_message(msg, from_addr=s.sender, to_addrs=list(s.recipients))
