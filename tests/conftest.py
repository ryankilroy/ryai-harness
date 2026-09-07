"""Shared pytest fixtures.

``stub_backend`` is the single stubbed OpenAI-compatible HTTP-server test
seam (issue #13): a stand-in Backend endpoint for exercising an Adapter's
``render``/``parse`` round trip through real HTTP, without a live GPU.
Every Backend-adapter ticket after this one reuses it — nothing here is
Qwen3-Coder-specific; dialect knowledge lives only in fixture *data*
(tests/fixtures/qwen3_coder/), never in this server.

stdlib only (``http.server``, ``json``, ``threading``) — no HTTP client or
server dependency is added anywhere in this project (ADR 0001: a plain
OpenAI-compatible endpoint needs none).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


class _State:
    """Mutable box shared between the test thread and the handler thread.

    One HTTP server per test (see the ``stub_backend`` fixture), so there
    is no cross-test sharing to race on; the split from ``StubBackend``
    exists only so the dynamically-built handler class has somewhere to
    read/write that isn't itself.
    """

    def __init__(self) -> None:
        self.status = 200
        self.body: dict[str, Any] = {}
        self.last_request_body: dict[str, Any] | None = None
        self.last_request_path: str | None = None


class _Handler(BaseHTTPRequestHandler):
    state: _State  # bound per-instance by StubBackend via a subclass

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return  # keep test output free of default per-request access logs

    def do_POST(self) -> None:  # noqa: N802 -- http.server's naming convention
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        self.state.last_request_path = self.path
        try:
            self.state.last_request_body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.state.last_request_body = None

        payload = json.dumps(self.state.body).encode("utf-8")
        self.send_response(self.state.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class StubBackend:
    """A single-response-at-a-time stand-in for an OpenAI-compatible endpoint.

    Bound to an ephemeral port (``0``) so parallel/CI runs never collide
    on a fixed port; the real bound port is read back off the live socket
    via ``url`` -- nothing here hardcodes or guesses a port number.

    Call ``set_response`` with a fixture body before each request a test
    makes; the next ``POST`` to any path returns that body/status.
    ``last_request_body`` holds the most recently received request,
    decoded, so a test can assert on what ``render()`` actually put on
    the wire (e.g. that a structural-tag constraint is present).
    """

    def __init__(self) -> None:
        self._state = _State()
        handler = type("_BoundHandler", (_Handler,), {"state": self._state})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def set_response(self, body: dict[str, Any], status: int = 200) -> None:
        self._state.status = status
        self._state.body = body

    @property
    def last_request_body(self) -> dict[str, Any] | None:
        return self._state.last_request_body

    @property
    def last_request_path(self) -> str | None:
        return self._state.last_request_path

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def stub_backend() -> Iterator[StubBackend]:
    """Yield a live StubBackend; always torn down, even on test failure."""
    backend = StubBackend()
    try:
        yield backend
    finally:
        backend.shutdown()
