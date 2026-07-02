"""LawPay / AffiniPay (8am) concrete payment processor.

Talks to the **Payment Gateway API** (the only AffiniPay API we use) over HTTPS
with HTTP Basic auth (secret key, empty password). Maps AffiniPay's request and
response shapes onto the normalized contract in `base`.

API facts this adapter relies on (developers.8am.com, Payment Gateway API):
- Auth: HTTP Basic, ``secret_key:`` (empty password). Test keys hit only test
  accounts, live keys only live.
- Charge: ``POST /v1/charges`` with ``amount`` (integer cents), ``currency``,
  ``method`` (the one-time hosted-fields token, passed as a **bare string**),
  optional ``account_id`` (omitted → gateway auto-selects the primary
  merchant/eCheck account by method type), ``reference`` (≤128 chars).
- Retrieve: ``GET /v1/transactions/{id}``.
- Refund: ``POST /v1/charges/{id}/refund`` ``{"amount": <cents>}``.
- Void:   ``POST /v1/transactions/{id}/void``.
- Decline: HTTP ``422`` with ``{"messages": [{"code","context","level",
  "message"}]}``.
- Statuses: card ``AUTHORIZED``/``COMPLETED`` (≈synchronous); ACH/eCheck
  ``AUTHORIZED → PENDING → COMPLETED`` or ``FAILED``/``RETURNED`` days later.

Webhook authenticity: AffiniPay documents no signature header and warns "anyone
can send data to the URL." So `verify_and_parse_webhook` treats the payload as
an untrusted *pointer* — it extracts the transaction id and **re-fetches the
transaction from the API** (with our secret key) to get the authoritative
status. IP-allowlisting is enforced at the view layer (Piece 3).

NOTE: the sandbox merchant has no test deposit accounts provisioned yet, so the
charge/refund/webhook *network* paths below are written to the documented API
but not yet exercised live. Items marked "SANDBOX-VERIFY" are the ones to
confirm once test accounts exist.
"""

import json
from decimal import Decimal

import requests
from django.conf import settings

from .base import (
    BANK,
    CARD,
    FAILED,
    PENDING,
    REFUNDED,
    RETURNED,
    SUCCEEDED,
    VOIDED,
    ChargeError,
    ChargeResult,
    ClientConfig,
    PaymentProcessor,
    ProcessorConfigError,
    WebhookEvent,
    WebhookVerificationError,
)

# Hosted-fields client SDK (rendered into the public payment page in Piece 2).
HOSTED_FIELDS_URL = "https://cdn.affinipay.com/hostedfields/1.5.3/fieldGen_1.5.3.js"

_TIMEOUT = 30  # seconds

# AffiniPay native status -> normalized status. Card auth means funds are
# secured (settles to COMPLETED); ACH auth is still in flight — so AUTHORIZED is
# resolved by method type in `_normalize`.
_STATUS_MAP = {
    "COMPLETED": SUCCEEDED,
    "PENDING": PENDING,
    "FAILED": FAILED,
    "RETURNED": RETURNED,
    "VOIDED": VOIDED,
}


def _to_cents(amount) -> int:
    """Decimal/float dollars -> integer cents (AffiniPay charge amount unit)."""
    return int((Decimal(str(amount)) * 100).to_integral_value())


class LawPayProcessor(PaymentProcessor):
    name = "lawpay"

    def __init__(self, *, secret_key=None, public_key=None, api_base=None):
        self.secret_key = (
            secret_key if secret_key is not None else settings.LAWPAY_SECRET_KEY
        )
        self.public_key = (
            public_key if public_key is not None else settings.LAWPAY_PUBLIC_KEY
        )
        # Deposit account ids per (destination, method). A charge picks the right
        # one so funds land in operating vs trust — and because AffiniPay keeps
        # card and eCheck in separate accounts. Blank → the gateway auto-selects
        # the primary account for the method.
        self.operating_card_account_id = settings.LAWPAY_OPERATING_CARD_ACCOUNT_ID
        self.operating_echeck_account_id = settings.LAWPAY_OPERATING_ECHECK_ACCOUNT_ID
        self.trust_card_account_id = settings.LAWPAY_TRUST_CARD_ACCOUNT_ID
        self.trust_echeck_account_id = settings.LAWPAY_TRUST_ECHECK_ACCOUNT_ID
        self.api_base = (api_base or settings.LAWPAY_API_BASE).rstrip("/")
        if not self.secret_key:
            raise ProcessorConfigError("LAWPAY_SECRET_KEY is not configured.")

    def account_id_for(self, *, method, trust=False):
        """Deposit account id for a charge: trust vs operating × card vs eCheck.
        Invoices/balances are operating (trust=False); a trust deposit passes
        trust=True. Returns "" to let the gateway auto-select."""
        if trust:
            return (
                self.trust_echeck_account_id
                if method == BANK
                else self.trust_card_account_id
            )
        return (
            self.operating_echeck_account_id
            if method == BANK
            else self.operating_card_account_id
        )

    # --- contract --------------------------------------------------------
    def client_config(self, invoice) -> ClientConfig:
        return self.client_config_for(
            amount_cents=_to_cents(invoice.amount_remaining),
            reference=f"Invoice {invoice.id}",
        )

    def client_config_for(
        self, *, amount_cents, reference, trust=False
    ) -> ClientConfig:
        return ClientConfig(
            processor=self.name,
            public_key=self.public_key,
            amount_cents=amount_cents,
            reference=reference,
            methods=[CARD, BANK],
            hosted_fields_url=HOSTED_FIELDS_URL,
        )

    def charge(
        self,
        *,
        token,
        amount_cents,
        reference,
        method,
        idempotency_key=None,
        metadata=None,
        trust=False,
        client=None,
        matter=None,
    ) -> ChargeResult:
        payload = {
            "amount": int(amount_cents),
            "currency": "USD",
            "method": token,  # one-time hosted-fields token, bare string
            "reference": (reference or "")[:128],
        }
        # Invoices/balances deposit to operating; the method picks card vs eCheck.
        account_id = self.account_id_for(method=method, trust=trust)
        if account_id:
            payload["account_id"] = account_id

        headers = {}
        if idempotency_key:
            # SANDBOX-VERIFY: AffiniPay does not document an idempotency header;
            # unknown headers are ignored, and Piece 3 also de-dups on the
            # invoice reference. Sent here as defence-in-depth.
            headers["Idempotency-Key"] = idempotency_key

        resp = self._request("POST", "/v1/charges", json_body=payload, headers=headers)
        data = self._json(resp)
        if resp.status_code == 422:
            code, message = self._first_message(data)
            raise ChargeError(message or "Charge was declined.", code=code, raw=data)
        self._raise_for_status(resp, data, "Charge failed")
        return self._result(data)

    def fetch_transaction(self, transaction_id) -> ChargeResult:
        resp = self._request("GET", f"/v1/transactions/{transaction_id}")
        data = self._json(resp)
        if resp.status_code == 404:
            raise ChargeError(
                f"Unknown transaction {transaction_id!r}", code="not_found", raw=data
            )
        self._raise_for_status(resp, data, "Fetch failed")
        return self._result(data)

    def list_merchant_accounts(self) -> dict:
        """GET /v1/merchant → the merchant and its deposit accounts.

        Read-only. Each entry in the ``merchant_accounts`` array carries ``id``,
        ``name`` and a ``trust_account`` boolean (true → trust, false →
        operating); ``ach_accounts`` lists eCheck accounts. Used to discover the
        account ids to pin as LAWPAY_{OPERATING,TRUST}_{CARD,ECHECK}_ACCOUNT_ID
        so a charge can target the right account. A test key returns test
        accounts only.
        """
        resp = self._request("GET", "/v1/merchant")
        data = self._json(resp)
        self._raise_for_status(resp, data, "Could not list merchant accounts")
        return data

    def verify_and_parse_webhook(self, request) -> WebhookEvent:
        """Untrusted payload in → authoritative event out.

        The body is only used to learn *which* transaction to look at; the
        returned status comes from re-fetching that transaction from the API.
        """
        try:
            body = json.loads(request.body or b"{}")
        except (ValueError, TypeError) as exc:
            raise WebhookVerificationError(f"Bad webhook body: {exc}") from exc

        event = self._first_event(body)
        if event is None:
            raise WebhookVerificationError("Webhook contained no event.")
        data = event.get("data") or {}
        txn_id = data.get("id") or data.get("transaction_id")
        if not txn_id:
            raise WebhookVerificationError("Webhook event has no transaction id.")

        # Re-fetch to confirm — this is the trust boundary, not the payload.
        try:
            confirmed = self.fetch_transaction(txn_id)
        except ChargeError as exc:
            raise WebhookVerificationError(
                f"Could not confirm transaction {txn_id!r}: {exc}"
            ) from exc

        return WebhookEvent(
            processor=self.name,
            event_id=str(event.get("id") or ""),
            transaction_id=txn_id,
            status=confirmed.status,
            amount_cents=confirmed.amount_cents,
            raw=body,
        )

    def refund(
        self, *, transaction_id, amount_cents=None, reference=None
    ) -> ChargeResult:
        payload = {}
        if amount_cents is not None:
            payload["amount"] = int(amount_cents)
        if reference:
            payload["reference"] = reference[:128]
        resp = self._request(
            "POST", f"/v1/charges/{transaction_id}/refund", json_body=payload
        )
        data = self._json(resp)
        if resp.status_code == 422:
            code, message = self._first_message(data)
            raise ChargeError(message or "Refund was declined.", code=code, raw=data)
        self._raise_for_status(resp, data, "Refund failed")
        return self._result(data)

    # --- internals -------------------------------------------------------
    def _request(self, verb, path, *, json_body=None, headers=None):
        url = f"{self.api_base}{path}"
        try:
            return requests.request(
                verb,
                url,
                auth=(self.secret_key, ""),
                json=json_body,
                headers=headers or {},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            # Network/transport failure — surface as a charge error so callers
            # treat it as "no charge happened" (it is safe to retry).
            raise ChargeError(
                f"Could not reach payment processor: {exc}", code="network"
            ) from exc

    @staticmethod
    def _json(resp) -> dict:
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {"data": data}

    @staticmethod
    def _first_message(data):
        """Pull (code, message) from AffiniPay's ``{"messages": [...]}`` body."""
        messages = (data or {}).get("messages") or []
        if messages and isinstance(messages[0], dict):
            return messages[0].get("code"), messages[0].get("message")
        return None, None

    @staticmethod
    def _first_event(body):
        """AffiniPay posts ``{"events": [...]}``; tolerate a bare event too."""
        if isinstance(body, dict) and isinstance(body.get("events"), list):
            return body["events"][0] if body["events"] else None
        if isinstance(body, dict) and ("data" in body or "type" in body):
            return body
        return None

    def _raise_for_status(self, resp, data, prefix):
        if resp.status_code >= 300:
            code, message = self._first_message(data)
            raise ChargeError(
                message or f"{prefix} (HTTP {resp.status_code}).",
                code=code or str(resp.status_code),
                raw=data,
            )

    def _result(self, data) -> ChargeResult:
        status, norm_method = self._normalize(data)
        return ChargeResult(
            processor=self.name,
            transaction_id=str(data.get("id") or ""),
            status=status,
            amount_cents=int(data.get("amount") or 0),
            method=norm_method,
            raw=data,
        )

    @staticmethod
    def _normalize(data):
        raw_status = (data.get("status") or "").upper()
        txn_type = (data.get("type") or "").upper()
        method_type = ((data.get("method") or {}).get("type") or "").lower()
        norm_method = CARD if method_type == "card" else BANK

        if txn_type == "REFUND":
            status = REFUNDED
        elif raw_status == "AUTHORIZED":
            # Card auth = funds secured; ACH auth = still settling.
            status = SUCCEEDED if norm_method == CARD else PENDING
        else:
            # Unknown statuses fall back to PENDING; a webhook re-fetch resolves
            # them rather than us guessing wrong.
            status = _STATUS_MAP.get(raw_status, PENDING)

        # A fully-refunded charge reads as refunded for our purposes.
        amount = int(data.get("amount") or 0)
        refunded = int(data.get("amount_refunded") or 0)
        if status == SUCCEEDED and amount and refunded >= amount:
            status = REFUNDED

        return status, norm_method
