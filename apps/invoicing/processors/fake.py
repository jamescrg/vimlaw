"""In-process fake payment processor for development and tests.

Simulates the real LawPay/AffiniPay lifecycle so Pieces B (public payment page)
and C (recording + webhooks/reconciliation) can be built and exercised
end-to-end before sandbox credentials exist:

- **Card** charges settle immediately (`SUCCEEDED`).
- **ACH/eCheck** charges are accepted as `PENDING`, then later move to
  `SUCCEEDED` *or* `RETURNED` — the asynchronous settlement that makes the
  reconciliation path necessary.

Outcomes are driven by special token strings so tests are deterministic:

    fake-ok            -> normal (card: SUCCEEDED; bank: PENDING)
    fake-decline       -> ChargeError at charge time
    fake-ach-return    -> bank charge accepted PENDING, destined to RETURN
    fake-ach-fail      -> bank charge accepted PENDING, destined to FAIL

Drive the asynchronous step from dev/tests with `simulate_settlement(txn_id)`
(advances PENDING bank charges to their destiny) or `simulate_event(txn_id,
status)` (force any status). Both return a `WebhookEvent`, and the matching
status is what a subsequent `verify_and_parse_webhook`/`fetch_transaction`
reports — mirroring "re-fetch to confirm".

State lives in a module-level registry: process-local and non-persistent, which
is exactly right for a fake (a fresh process starts empty).
"""

import itertools
import json
from uuid import uuid4

from .base import (
    ACCEPTED_STATUSES,
    BANK,
    CARD,
    FAILED,
    PENDING,
    REFUNDED,
    RETURNED,
    SUCCEEDED,
    ChargeError,
    ChargeResult,
    ClientConfig,
    PaymentProcessor,
    WebhookEvent,
    WebhookVerificationError,
)

# Process-local transaction registry: {transaction_id: dict}
_TRANSACTIONS: dict[str, dict] = {}
_EVENT_COUNTER = itertools.count(1)

# Token strings that script a charge's behaviour.
_DECLINE_TOKEN = "fake-decline"
_ACH_RETURN_TOKEN = "fake-ach-return"
_ACH_FAIL_TOKEN = "fake-ach-fail"


def reset():
    """Clear the registry — handy between tests."""
    _TRANSACTIONS.clear()


class FakeProcessor(PaymentProcessor):
    name = "fake"

    HOSTED_FIELDS_URL = "https://example.test/fake-hosted-fields.js"

    def client_config(self, invoice) -> ClientConfig:
        amount_cents = int(round(float(invoice.amount_remaining) * 100))
        return self.client_config_for(
            amount_cents=amount_cents, reference=f"Invoice {invoice.id}"
        )

    def client_config_for(
        self, *, amount_cents, reference, trust=False
    ) -> ClientConfig:
        return ClientConfig(
            processor=self.name,
            public_key="fake_public_key",
            amount_cents=amount_cents,
            reference=reference,
            methods=[CARD, BANK],
            hosted_fields_url=self.HOSTED_FIELDS_URL,
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
        if token == _DECLINE_TOKEN:
            raise ChargeError(
                "Card declined (fake).", code="declined", raw={"token": token}
            )

        # Globally-unique id like a real processor (avoids collisions across
        # separate processes / test runs).
        txn_id = f"fake_{method}_{uuid4().hex[:16]}"

        # Card settles immediately; bank is accepted but provisional.
        if method == CARD:
            status = SUCCEEDED
            destiny = SUCCEEDED
        else:  # BANK / ACH
            status = PENDING
            if token == _ACH_RETURN_TOKEN:
                destiny = RETURNED
            elif token == _ACH_FAIL_TOKEN:
                destiny = FAILED
            else:
                destiny = SUCCEEDED

        _TRANSACTIONS[txn_id] = {
            "id": txn_id,
            "status": status,
            "destiny": destiny,
            "amount_cents": amount_cents,
            "amount_refunded": 0,
            "method": method,
            "reference": reference,
            "idempotency_key": idempotency_key,
            "metadata": metadata or {},
            # Deposited into the bank yet? Advanced by a webhook body `settled:true`
            # (or simulate_deposit) — mirrors the processor's DEPOSITED state.
            "settled": False,
        }
        return self._result(txn_id)

    def fetch_transaction(self, transaction_id) -> ChargeResult:
        if transaction_id not in _TRANSACTIONS:
            raise ChargeError(
                f"Unknown transaction {transaction_id!r}", code="not_found"
            )
        return self._result(transaction_id)

    def verify_and_parse_webhook(self, request) -> WebhookEvent:
        """Parse a simulated webhook POST body `{transaction_id, status?}`.

        Mirrors the real "re-fetch to confirm" design: the body is only a
        pointer; the returned event's status comes from the registry (our
        source of truth), not from whatever the body claims.
        """
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, TypeError) as exc:
            raise WebhookVerificationError(f"Bad webhook body: {exc}") from exc

        txn_id = payload.get("transaction_id")
        if not txn_id or txn_id not in _TRANSACTIONS:
            raise WebhookVerificationError(
                f"Unknown transaction in webhook: {txn_id!r}"
            )

        # If the body asks to advance the transaction, honour it (dev/test
        # convenience), then report the confirmed status from the registry.
        requested = payload.get("status")
        if requested:
            _TRANSACTIONS[txn_id]["status"] = requested
        if payload.get("settled"):
            _TRANSACTIONS[txn_id]["settled"] = True

        return self._event(txn_id)

    def refund(
        self, *, transaction_id, amount_cents=None, reference=None
    ) -> ChargeResult:
        txn = _TRANSACTIONS.get(transaction_id)
        if txn is None:
            raise ChargeError(
                f"Unknown transaction {transaction_id!r}", code="not_found"
            )
        refund_amount = (
            amount_cents if amount_cents is not None else txn["amount_cents"]
        )
        txn["amount_refunded"] = min(
            txn["amount_cents"], txn["amount_refunded"] + refund_amount
        )
        if txn["amount_refunded"] >= txn["amount_cents"]:
            txn["status"] = REFUNDED
        return self._result(transaction_id)

    # --- Dev/test helpers (not part of the abstract contract) ------------
    def simulate_settlement(self, transaction_id) -> WebhookEvent:
        """Advance an accepted PENDING charge to its scripted destiny
        (SUCCEEDED / RETURNED / FAILED), as a settlement webhook would."""
        txn = _TRANSACTIONS[transaction_id]
        if txn["status"] in ACCEPTED_STATUSES:
            txn["status"] = txn["destiny"]
        return self._event(transaction_id)

    def simulate_event(self, transaction_id, status) -> WebhookEvent:
        """Force `transaction_id` to `status` and return the matching event."""
        _TRANSACTIONS[transaction_id]["status"] = status
        return self._event(transaction_id)

    # --- internals -------------------------------------------------------
    def _result(self, transaction_id) -> ChargeResult:
        txn = _TRANSACTIONS[transaction_id]
        return ChargeResult(
            processor=self.name,
            transaction_id=transaction_id,
            status=txn["status"],
            amount_cents=txn["amount_cents"],
            method=txn["method"],
            raw=dict(txn),
            settled=txn.get("settled", False),
        )

    def _event(self, transaction_id) -> WebhookEvent:
        txn = _TRANSACTIONS[transaction_id]
        return WebhookEvent(
            processor=self.name,
            event_id=f"fake_evt_{next(_EVENT_COUNTER)}",
            transaction_id=transaction_id,
            status=txn["status"],
            amount_cents=txn["amount_cents"],
            raw=dict(txn),
            settled=txn.get("settled", False),
        )
