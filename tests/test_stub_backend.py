"""Tests for the reusable stub OpenAI-compatible HTTP-server fixture
(tests/conftest.py's ``stub_backend``) -- exercised directly, independent
of any particular Adapter, so this reusable test seam is proven sound on
its own before any Adapter is built against it. Every HTTP-touching test
here carries a hard timeout (``urlopen(..., timeout=2)``); none may block
on a socket.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def _post(url: str, payload: dict[str, object] | None = None) -> tuple[int, bytes]:
    data = json.dumps(payload if payload is not None else {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.status, resp.read()


def test_serves_the_configured_response_body(stub_backend) -> None:  # type: ignore[no-untyped-def]
    stub_backend.set_response({"hello": "world"})

    _status, body = _post(f"{stub_backend.url}/v1/chat/completions")

    assert json.loads(body) == {"hello": "world"}


def test_binds_an_ephemeral_port_not_a_hardcoded_one(stub_backend) -> None:  # type: ignore[no-untyped-def]
    port = int(stub_backend.url.rsplit(":", 1)[-1])

    assert port != 0
    assert port > 1024  # never the port a fixed/well-known value would pick


def test_captures_the_last_request_body_and_path_for_assertions(stub_backend) -> None:  # type: ignore[no-untyped-def]
    stub_backend.set_response({"ok": True})
    payload = {"messages": [{"role": "user", "content": "hi"}]}

    _post(f"{stub_backend.url}/v1/chat/completions", payload)

    assert stub_backend.last_request_body == payload
    assert stub_backend.last_request_path == "/v1/chat/completions"


def test_returns_a_configured_non_200_status(stub_backend) -> None:  # type: ignore[no-untyped-def]
    stub_backend.set_response({"error": "nope"}, status=403)

    try:
        _post(f"{stub_backend.url}/v1/chat/completions")
        raise AssertionError("expected an HTTPError for a configured 403 response")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
        assert json.loads(exc.read()) == {"error": "nope"}
