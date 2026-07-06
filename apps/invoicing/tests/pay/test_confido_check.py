"""Tests for the `confido_check` read-only pre-flight command. The HTTP layer
(`requests.post`) is mocked, so no network and no charge."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

OP_ID = "op-123"
TRUST_ID = "tr-456"

_ACCOUNTS_OK = {
    "data": {
        "bankAccountsList": {
            "bankAccounts": [
                {
                    "id": OP_ID,
                    "nickname": "Operating",
                    "category": "operating",
                    "isDefault": True,
                    "isFeeAccount": True,
                },
                {
                    "id": TRUST_ID,
                    "nickname": "Trust",
                    "category": "trust",
                    "isDefault": False,
                    "isFeeAccount": False,
                },
            ]
        }
    }
}
_SESSION_OK = {
    "data": {
        "paymentSessionCreate": {"paymentSessionToken": "pay_public_production_abc123"}
    }
}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _router(handlers):
    def post(url, headers=None, json=None, timeout=None):
        query = json["query"]
        for sub, payload in handlers:
            if sub in query:
                return _Resp(payload)
        raise AssertionError(f"unexpected query: {query}")

    return post


def _configure(
    settings,
    *,
    operating=OP_ID,
    trust=TRUST_ID,
    base="https://api.gravity-legal.com/v2",
):
    settings.CONFIDO_API_KEY = "f_secret_production_x"
    settings.CONFIDO_API_BASE = base
    settings.CONFIDO_OPERATING_BANK_ACCOUNT_ID = operating
    settings.CONFIDO_TRUST_BANK_ACCOUNT_ID = trust


def _run(handlers):
    out = StringIO()
    with patch(
        "apps.invoicing.processors.confido.requests.post", side_effect=_router(handlers)
    ):
        call_command("confido_check", stdout=out, no_color=True)
    return out.getvalue()


def test_confido_check_passes(settings):
    _configure(settings)
    text = _run(
        [("bankAccountsList", _ACCOUNTS_OK), ("paymentSessionCreate", _SESSION_OK)]
    )
    assert "[LIVE]" in text
    assert "Auth OK — 2 bank account(s)" in text
    assert "operating id matches" in text
    assert "trust id matches" in text
    assert "operating session minted" in text
    assert "trust session minted" in text
    assert "PRE-FLIGHT PASSED" in text


def test_confido_check_flags_wrong_account_id(settings):
    _configure(settings, trust="not-a-real-id")
    text = _run(
        [("bankAccountsList", _ACCOUNTS_OK), ("paymentSessionCreate", _SESSION_OK)]
    )
    assert "trust id not-a-real-id not found" in text
    assert "PRE-FLIGHT FAILED" in text


def test_confido_check_warns_on_sandbox(settings):
    _configure(settings, base="https://api.sandbox.gravity-legal.com/v2")
    text = _run(
        [("bankAccountsList", _ACCOUNTS_OK), ("paymentSessionCreate", _SESSION_OK)]
    )
    assert "[SANDBOX]" in text
    assert "Still pointed at SANDBOX" in text
