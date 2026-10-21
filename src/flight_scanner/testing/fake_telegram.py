"""A stand-in for the Telegram Bot API on 127.0.0.1, for tests. Never talks to Telegram.

with FakeTelegram() as tg:                    # serves http://127.0.0.1:<port>/bot<token>/<method>
    env = {"TELEGRAM_API_URL": tg.url, ...}
    tg.press(alert_id=41, rating="up")        # queue a 👍 callback_query for getUpdates
    tg.calls                                  # [(method, json_body), ...] in arrival order
    tg.fail_next("sendMessage")               # the next call of that method gets ok=false
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeTelegram:
    def __init__(self, token: str = "123:test-token", chat_id: int = 5550001):
        self.token = token
        self.chat_id = chat_id
        self.calls: list[tuple[str, dict]] = []
        self._updates: list[dict] = []
        self._next_update_id = 1000
        self._next_message_id = 1
        self._failing: set[str] = set()
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeTelegram:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def calls_to(self, method: str) -> list[dict]:
        return [body for m, body in self.calls if m == method]

    def fail_next(self, method: str) -> None:
        self._failing.add(method)

    def press(self, alert_id: int, rating: str, chat_id: int | None = None) -> None:
        """The owner taps 👍/👎 under the Alert message (data as the notifier wrote it)."""
        self.press_raw(f"rate:{alert_id}:{rating}", chat_id)

    def press_raw(self, data: str, chat_id: int | None = None) -> None:
        with self._lock:
            uid = self._next_update_id
            self._next_update_id += 1
            chat = {"id": self.chat_id if chat_id is None else chat_id, "type": "private"}
            self._updates.append(
                {
                    "update_id": uid,
                    "callback_query": {
                        "id": f"cb{uid}",
                        "from": {"id": chat["id"], "is_bot": False, "first_name": "Owner"},
                        "message": {"message_id": 1, "chat": chat, "date": 0},
                        "chat_instance": "x",
                        "data": data,
                    },
                }
            )

    def _respond(self, method: str, body: dict) -> tuple[int, dict]:
        with self._lock:
            self.calls.append((method, body))
            if method in self._failing:
                self._failing.discard(method)
                return 400, {"ok": False, "error_code": 400, "description": "Bad Request: test"}
            if method == "sendMessage":
                mid = self._next_message_id
                self._next_message_id += 1
                return 200, {"ok": True, "result": {"message_id": mid, "chat": {"id": 0}}}
            if method == "getUpdates":
                offset = body.get("offset", 0)
                # Telegram forgets updates below the offset once they are acknowledged.
                self._updates = [u for u in self._updates if u["update_id"] >= offset]
                return 200, {"ok": True, "result": list(self._updates)}
            return 200, {"ok": True, "result": True}

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                prefix = f"/bot{fake.token}/"
                if not self.path.startswith(prefix):
                    self._reply(404, {"ok": False, "error_code": 404, "description": "Not Found"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._reply(*fake._respond(self.path[len(prefix) :], body))

            def _reply(self, status: int, doc: dict) -> None:
                raw = json.dumps(doc).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args) -> None:
                pass

        return Handler
