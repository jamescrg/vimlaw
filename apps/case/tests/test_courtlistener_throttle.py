"""The CourtListener request throttle (shared by citation vetting and the
research pipeline)."""


def test_throttle_retries_429_with_retry_after(monkeypatch):
    from apps.case import courtlistener_throttle as throttle

    sleeps = []
    monkeypatch.setattr(throttle.time, "sleep", lambda s: sleeps.append(s))

    class Resp:
        def __init__(self, status, headers=None):
            self.status_code = status
            self.headers = headers or {}

    responses = [Resp(429, {"Retry-After": "3"}), Resp(200)]
    monkeypatch.setattr(
        throttle.requests, "request", lambda m, u, **k: responses.pop(0)
    )

    response = throttle.throttled_request("get", "https://x")
    assert response.status_code == 200
    assert 3.0 in sleeps


def test_throttle_never_retries_400(monkeypatch):
    from apps.case import courtlistener_throttle as throttle

    monkeypatch.setattr(throttle.time, "sleep", lambda s: None)
    calls = []

    class Resp:
        status_code = 400
        headers = {}

    monkeypatch.setattr(
        throttle.requests, "request", lambda m, u, **k: calls.append(1) or Resp()
    )
    assert throttle.throttled_request("get", "https://x").status_code == 400
    assert len(calls) == 1
