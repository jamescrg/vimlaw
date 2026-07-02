"""Stripe concrete payment processor.

Direct, single-account integration: the firm owns its Stripe account and
provides its own keys (this is an open-source, self-hosted app — one firm per
instance). The client collects card details with Stripe Elements and tokenizes
them into a PaymentMethod id; we confirm a PaymentIntent server-side with that
id, so the existing "tokenize -> POST token -> server charges" flow is unchanged.

Cards confirm synchronously (``allow_redirects="never"``), so a card requiring
3-D Secure is declined rather than left half-authenticated — full SCA/redirect
support is a follow-up. ACH (``us_bank_account``) is a later addition.

Unlike LawPay, Stripe webhooks are cryptographically signed, so
``verify_and_parse_webhook`` verifies the signature instead of re-fetching.

The Stripe SDK returns ``StripeObject`` instances (not dicts and, in v15,
without a ``.get()``), so ``_to_plain`` normalizes them to plain dicts before we
read fields.
"""

from decimal import Decimal

import stripe
from django.conf import settings

from .base import (
    BANK,
    CARD,
    FAILED,
    PENDING,
    REFUNDED,
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

# Stripe PaymentIntent status -> normalized status.
_STATUS_MAP = {
    "succeeded": SUCCEEDED,
    "processing": PENDING,  # ACH in flight
    "requires_payment_method": FAILED,  # the last confirm attempt failed
    "canceled": VOIDED,
}

# Stripe webhook event type -> normalized status (only the ones we act on).
_EVENT_STATUS = {
    "payment_intent.succeeded": SUCCEEDED,
    "payment_intent.processing": PENDING,
    "payment_intent.payment_failed": FAILED,
    "payment_intent.canceled": VOIDED,
    "charge.refunded": REFUNDED,
}


def _to_cents(amount) -> int:
    """Decimal/float dollars -> integer cents."""
    return int((Decimal(str(amount)) * 100).to_integral_value())


def _to_plain(obj) -> dict:
    """A Stripe object -> plain dict (test mocks pass dicts straight through)."""
    return obj if isinstance(obj, dict) else obj.to_dict()


class StripeProcessor(PaymentProcessor):
    name = "stripe"

    def __init__(self, *, secret_key=None, publishable_key=None, webhook_secret=None):
        self.secret_key = (
            secret_key if secret_key is not None else settings.STRIPE_SECRET_KEY
        )
        self.publishable_key = (
            publishable_key
            if publishable_key is not None
            else settings.STRIPE_PUBLISHABLE_KEY
        )
        self.webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else settings.STRIPE_WEBHOOK_SECRET
        )
        if not self.secret_key:
            raise ProcessorConfigError("STRIPE_SECRET_KEY is not configured.")

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
            public_key=self.publishable_key,
            amount_cents=amount_cents,
            reference=reference,
            methods=[CARD, BANK],
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
    ) -> ChargeResult:
        params = {
            "amount": int(amount_cents),
            "currency": "usd",
            "payment_method": token,  # a Stripe PaymentMethod id (pm_...)
            "confirm": True,
            "description": (reference or "")[:200],
            "metadata": {"reference": reference or "", **(metadata or {})},
            # Synchronous confirm only — no redirect-based auth (3DS); a card
            # needing it is declined rather than left awaiting client action.
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
            "api_key": self.secret_key,
        }
        if idempotency_key:
            params["idempotency_key"] = idempotency_key
        try:
            intent = stripe.PaymentIntent.create(**params)
        except stripe.CardError as exc:
            raise ChargeError(
                exc.user_message or str(exc),
                code=getattr(exc, "code", "card_declined"),
                raw=getattr(exc, "json_body", None) or {},
            ) from exc
        except stripe.StripeError as exc:
            raise ChargeError(
                f"Charge could not be created: {exc}",
                code=getattr(exc, "code", "stripe_error"),
            ) from exc

        data = _to_plain(intent)
        if data.get("status") == "requires_action":
            raise ChargeError(
                "This card requires additional authentication; please try another.",
                code="requires_action",
                raw=data,
            )
        return self._result(data)

    def fetch_transaction(self, transaction_id) -> ChargeResult:
        try:
            intent = stripe.PaymentIntent.retrieve(
                transaction_id, api_key=self.secret_key
            )
        except stripe.InvalidRequestError as exc:
            raise ChargeError(
                f"Unknown transaction {transaction_id!r}", code="not_found"
            ) from exc
        except stripe.StripeError as exc:
            raise ChargeError(f"Fetch failed: {exc}", code="stripe_error") from exc
        return self._result(_to_plain(intent))

    def verify_and_parse_webhook(self, request) -> WebhookEvent:
        """Verify Stripe's signature and normalize the event. The signed payload
        IS the trust boundary (no re-fetch needed)."""
        signature = getattr(request, "signature", "") or ""
        try:
            event = stripe.Webhook.construct_event(
                request.body, signature, self.webhook_secret
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise WebhookVerificationError(f"Bad Stripe webhook: {exc}") from exc

        status = _EVENT_STATUS.get(event["type"])
        if status is None:
            raise WebhookVerificationError(f"Unhandled Stripe event {event['type']!r}")

        # payment_intent.* events carry the PI; charge.* carry a charge whose
        # `payment_intent` is the id we stored as processor_txn_id.
        obj = _to_plain(event["data"]["object"])
        if obj.get("object") == "payment_intent":
            txn_id = obj.get("id")
        else:
            txn_id = obj.get("payment_intent")
        if not txn_id:
            raise WebhookVerificationError("Stripe event has no payment_intent id.")
        amount = obj.get("amount")

        return WebhookEvent(
            processor=self.name,
            event_id=str(event["id"]),
            transaction_id=str(txn_id),
            status=status,
            amount_cents=int(amount) if amount is not None else None,
            raw={"type": event["type"]},
        )

    def refund(
        self, *, transaction_id, amount_cents=None, reference=None
    ) -> ChargeResult:
        params = {"payment_intent": transaction_id, "api_key": self.secret_key}
        if amount_cents is not None:
            params["amount"] = int(amount_cents)
        try:
            stripe.Refund.create(**params)
        except stripe.StripeError as exc:
            raise ChargeError(f"Refund failed: {exc}", code="stripe_error") from exc
        # Reflect the resulting state back to the caller.
        return self.fetch_transaction(transaction_id)

    # --- internals -------------------------------------------------------
    def _result(self, data) -> ChargeResult:
        status, method = self._normalize(data)
        return ChargeResult(
            processor=self.name,
            transaction_id=str(data.get("id") or ""),
            status=status,
            amount_cents=int(data.get("amount") or 0),
            method=method,
            raw=dict(data),
        )

    @staticmethod
    def _normalize(data):
        status = _STATUS_MAP.get(data.get("status") or "", PENDING)
        pm_types = data.get("payment_method_types") or []
        method = BANK if pm_types == ["us_bank_account"] else CARD
        return status, method
