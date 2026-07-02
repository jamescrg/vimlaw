"""Unit tests for the Confido (Gravity Legal) GraphQL processor.

These mock the HTTP layer (`requests.post`) so they exercise the adapter's
GraphQL request shaping, status normalization, and HMAC webhook verification
without any network. They do NOT prove the live GraphQL field names — those are
marked SANDBOX-VERIFY in the adapter and confirmed against the sandbox.
"""

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.invoicing.processors.base import (
    BANK,
    CARD,
    PENDING,
    SUCCEEDED,
    ChargeError,
    ProcessorConfigError,
    WebhookVerificationError,
)
from apps.invoicing.processors.confido import ConfidoProcessor

WEBHOOK_SECRET = "whsec_test"


def proc(**kw):
    p = ConfidoProcessor(
        api_key="f_secret_test",
        api_base="https://api.test/v2",
        webhook_secret=WEBHOOK_SECRET,
        hosted_fields_url="https://js.test/hf.js",
        **kw,
    )
    return p


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _sign(raw: bytes) -> str:
    digest = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha512).digest()
    return base64.b64encode(digest).decode()


# --- config / factory ------------------------------------------------------
def test_requires_api_key():
    with pytest.raises(ProcessorConfigError):
        ConfidoProcessor(api_key="")


def test_factory_returns_confido(settings):
    settings.CONFIDO_API_KEY = "f_secret_test"
    from apps.invoicing.processors import get_processor

    assert isinstance(get_processor("confido"), ConfidoProcessor)


# --- client_config (session creation) --------------------------------------
def test_client_config_creates_session_operating():
    p = proc()
    p.operating_bank_account_id = "ba_operating"
    resp = _Resp(
        {"data": {"paymentSessionCreate": {"paymentSessionToken": "pay_pub_1"}}}
    )
    with patch(
        "apps.invoicing.processors.confido.requests.post", return_value=resp
    ) as m:
        cfg = p.client_config_for(amount_cents=5000, reference="Invoice 1")
    assert cfg.processor == "confido"
    assert cfg.public_key == "pay_pub_1"
    assert cfg.echeck is True
    assert cfg.hosted_fields_url == "https://js.test/hf.js"
    assert {CARD, BANK} == set(cfg.methods)
    # Operating: the operating bankAccountId is pinned (Confido has no default).
    variables = m.call_args.kwargs["json"]["variables"]
    assert variables["input"]["bankAccountId"] == "ba_operating"


def test_client_config_operating_requires_account_id():
    # No operating id configured -> config error (Confido has no auto-default).
    p = proc()
    p.operating_bank_account_id = ""
    with pytest.raises(ProcessorConfigError):
        p.client_config_for(amount_cents=5000, reference="Invoice 1")


def test_client_config_trust_requires_account_id():
    p = proc()
    p.trust_bank_account_id = ""
    with pytest.raises(ProcessorConfigError):
        p.client_config_for(amount_cents=5000, reference="Trust", trust=True)


def test_client_config_trust_pins_bank_account():
    p = proc()
    p.trust_bank_account_id = "ba_trust"
    resp = _Resp(
        {"data": {"paymentSessionCreate": {"paymentSessionToken": "pay_pub_t"}}}
    )
    with patch(
        "apps.invoicing.processors.confido.requests.post", return_value=resp
    ) as m:
        cfg = p.client_config_for(amount_cents=5000, reference="Trust", trust=True)
    assert cfg.public_key == "pay_pub_t"
    variables = m.call_args.kwargs["json"]["variables"]
    assert variables["input"]["bankAccountId"] == "ba_trust"


# --- charge (session completion) -------------------------------------------
def _complete(txn):
    return _Resp(
        {
            "data": {
                "paymentSessionComplete": {"status": "COMPLETED", "transactions": [txn]}
            }
        }
    )


def test_charge_card_pending_resolves_to_succeeded():
    txn = {
        "id": "txn_1",
        "status_v2": "PENDING",
        "amountProcessed": 5000,
        "paymentMethod": "CREDIT",
    }
    with patch(
        "apps.invoicing.processors.confido.requests.post", return_value=_complete(txn)
    ) as m:
        r = proc().charge(
            token="pay_pub_1",
            amount_cents=5000,
            reference="Invoice 1",
            method="card",
            metadata={"payer_email": "c@example.com"},
        )
    assert r.status == SUCCEEDED and r.accepted and r.transaction_id == "txn_1"
    assert r.method == CARD and r.amount_cents == 5000
    variables = m.call_args.kwargs["json"]["variables"]["input"]
    assert variables["amount"] == 5000
    assert variables["paymentSessionToken"] == "pay_pub_1"
    assert variables["method"] == "CREDIT"
    assert variables["payerEmail"] == "c@example.com"
    assert m.call_args.kwargs["headers"]["x-api-key"] == "f_secret_test"


def test_charge_bank_pending_stays_pending():
    txn = {
        "id": "txn_2",
        "status_v2": "PENDING",
        "amountProcessed": 5000,
        "paymentMethod": "ACH",
    }
    with patch(
        "apps.invoicing.processors.confido.requests.post", return_value=_complete(txn)
    ):
        r = proc().charge(token="pay", amount_cents=5000, reference="r", method="bank")
    assert r.status == PENDING and r.is_pending and r.method == BANK


def test_charge_deposited_is_succeeded():
    txn = {
        "id": "t",
        "status_v2": "DEPOSITED",
        "amountProcessed": 100,
        "paymentMethod": "CREDIT",
    }
    with patch(
        "apps.invoicing.processors.confido.requests.post", return_value=_complete(txn)
    ):
        r = proc().charge(token="p", amount_cents=100, reference="r", method="card")
    assert r.status == SUCCEEDED


def test_charge_graphql_error_raises_charge_error():
    resp = _Resp(
        {"errors": [{"message": "Card declined", "extensions": {"code": "declined"}}]}
    )
    with patch("apps.invoicing.processors.confido.requests.post", return_value=resp):
        with pytest.raises(ChargeError) as ei:
            proc().charge(token="p", amount_cents=100, reference="r", method="card")
    assert ei.value.code == "declined"
    assert "declined" in str(ei.value).lower()


def test_charge_no_transaction_raises():
    resp = _Resp(
        {"data": {"paymentSessionComplete": {"status": "FAILED", "transactions": []}}}
    )
    with patch("apps.invoicing.processors.confido.requests.post", return_value=resp):
        with pytest.raises(ChargeError) as ei:
            proc().charge(token="p", amount_cents=100, reference="r", method="card")
    assert ei.value.code == "not_completed"


def test_charge_network_error_raises():
    import requests

    with patch(
        "apps.invoicing.processors.confido.requests.post",
        side_effect=requests.RequestException("boom"),
    ):
        with pytest.raises(ChargeError) as ei:
            proc().charge(token="p", amount_cents=100, reference="r", method="card")
    assert ei.value.code == "network"


# --- fetch / refund --------------------------------------------------------
def test_fetch_transaction_maps_status():
    resp = _Resp(
        {
            "data": {
                "transaction": {
                    "id": "txn_9",
                    "status_v2": "DEPOSITED",
                    "amountProcessed": 1234,
                    "paymentMethod": "CREDIT",
                }
            }
        }
    )
    with patch("apps.invoicing.processors.confido.requests.post", return_value=resp):
        r = proc().fetch_transaction("txn_9")
    assert (
        r.transaction_id == "txn_9" and r.amount_cents == 1234 and r.status == SUCCEEDED
    )


def test_fetch_unknown_transaction_raises():
    resp = _Resp({"data": {"transaction": None}})
    with patch("apps.invoicing.processors.confido.requests.post", return_value=resp):
        with pytest.raises(ChargeError) as ei:
            proc().fetch_transaction("nope")
    assert ei.value.code == "not_found"


def test_refund_calls_transaction_refund():
    resp = _Resp(
        {
            "data": {
                "transactionRefund": {
                    "transaction": {
                        "id": "txn_r",
                        "status_v2": "REFUNDED",
                        "amountProcessed": 5000,
                        "paymentMethod": "CREDIT",
                    }
                }
            }
        }
    )
    with patch(
        "apps.invoicing.processors.confido.requests.post", return_value=resp
    ) as m:
        r = proc().refund(transaction_id="txn_r", amount_cents=5000)
    from apps.invoicing.processors.base import REFUNDED

    assert r.status == REFUNDED
    variables = m.call_args.kwargs["json"]["variables"]["input"]
    assert variables["transactionId"] == "txn_r" and variables["amount"] == 5000


# --- webhooks --------------------------------------------------------------
def test_webhook_verifies_signature_and_refetches():
    body = json.dumps(
        [
            {
                "data": {"transaction": {"id": "txn_1"}},
                "type": "transaction.deposited",
                "eventId": "evt_1",
            }
        ]
    ).encode()
    fetch = _Resp(
        {
            "data": {
                "transaction": {
                    "id": "txn_1",
                    "status_v2": "DEPOSITED",
                    "amountProcessed": 5000,
                    "paymentMethod": "CREDIT",
                }
            }
        }
    )
    with patch("apps.invoicing.processors.confido.requests.post", return_value=fetch):
        ev = proc().verify_and_parse_webhook(
            SimpleNamespace(body=body, signature=_sign(body))
        )
    assert ev.status == SUCCEEDED
    assert ev.transaction_id == "txn_1"
    assert ev.event_id == "evt_1"


def test_webhook_bad_signature_rejected():
    body = b"[]"
    with pytest.raises(WebhookVerificationError):
        proc().verify_and_parse_webhook(SimpleNamespace(body=body, signature="wrong"))


def test_webhook_ach_return_uses_original_transaction_id():
    body = json.dumps(
        [
            {
                "data": {
                    "originalTransaction": {"id": "txn_orig"},
                    "returnTransaction": {"id": "txn_ret"},
                },
                "type": "transaction.ach_returned",
                "eventId": "evt_2",
            }
        ]
    ).encode()
    fetch = _Resp(
        {
            "data": {
                "transaction": {
                    "id": "txn_orig",
                    "status_v2": "RETURNED",
                    "amountProcessed": 5000,
                    "paymentMethod": "ACH",
                }
            }
        }
    )
    from apps.invoicing.processors.base import RETURNED

    with patch("apps.invoicing.processors.confido.requests.post", return_value=fetch):
        ev = proc().verify_and_parse_webhook(
            SimpleNamespace(body=body, signature=_sign(body))
        )
    assert ev.status == RETURNED and ev.transaction_id == "txn_orig"
