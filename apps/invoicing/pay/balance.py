"""Matter "catch-up" payment: pay a matter's full open balance in one charge.

The client opens a tokenized balance link, sees the total they owe on the matter
(the sum of its open invoices), and pays it. We record one Payment on the matter
and apply it oldest-invoice-first across those invoices, reusing the existing
PaymentApplication auto-PAID behaviour. Deferred invoices are excluded — they are
not currently collectible.
"""

from decimal import Decimal

from django.utils import timezone

from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.invoicing.processors import CARD
from apps.trust.models import Transaction

# Statuses that are not part of a currently-payable balance.
_NOT_PAYABLE = ["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE", "DEFERRED"]


def matter_open_invoices(matter):
    """The matter's currently-payable invoices, oldest first — excludes deferred
    and non-billable statuses and anything already paid off."""
    invoices = (
        Invoice.objects.filter(matter=matter)
        .exclude(status__in=_NOT_PAYABLE)
        .order_by("date_issued")
    )
    return [inv for inv in invoices if inv.amount_remaining > 0]


def matter_balance_cents(matter) -> int:
    """Total currently owed on the matter, in integer cents."""
    total = sum(inv.amount_remaining for inv in matter_open_invoices(matter))
    return int(Decimal(total) * 100)


def request_charge_cents(payment_request) -> int:
    """Cents to charge for a payment request. A trust deposit charges the firm-set
    amount as-is (no balance to cap against); an operating request caps it at the
    matter's current open balance so it can never overpay."""
    requested = int(Decimal(payment_request.amount_requested) * 100)
    if payment_request.is_trust:
        return max(0, requested)
    live = matter_balance_cents(payment_request.matter)
    return max(0, min(requested, live))


def record_trust_deposit(client, result):
    """Record an accepted charge as a trust-ledger Deposit for the client.
    Idempotent on the processor transaction id. Created UNCONFIRMED — the firm
    confirms it in the trust workflow once it clears the trust account."""
    existing = Transaction.objects.filter(
        processor=result.processor, processor_txn_id=result.transaction_id
    ).first()
    if existing:
        return existing
    amount = Decimal(result.amount_cents) / Decimal(100)
    return Transaction.objects.create(
        contact=client,
        date=timezone.localdate(),
        type="Deposit",
        description=f"Online trust deposit · {result.processor} {result.transaction_id}",
        amount=amount,
        confirmed=False,
        entered=False,
        processor=result.processor,
        processor_txn_id=result.transaction_id,
        processor_status=result.status,
    )


def record_matter_balance_payment(matter, result):
    """Record an accepted charge as one Payment on the matter, applied
    oldest-invoice-first across its open invoices. Idempotent on the processor
    transaction id (a settlement webhook re-running this finds the same row)."""
    existing = Payment.objects.filter(
        processor=result.processor, processor_txn_id=result.transaction_id
    ).first()
    if existing:
        return existing

    amount = Decimal(result.amount_cents) / Decimal(100)
    method = "CARD" if result.method == CARD else "ACH"
    payment = Payment.objects.create(
        matter=matter,
        date=timezone.localdate(),
        amount=amount,
        payment_method=method,
        detail=f"Online payment · {result.processor}",
        processor=result.processor,
        processor_txn_id=result.transaction_id,
        processor_status=result.status,
    )

    remaining = amount
    for inv in matter_open_invoices(matter):
        if remaining <= 0:
            break
        applied = min(remaining, inv.amount_remaining)
        if applied > 0:
            # save() flips the invoice to PAID once amount_remaining hits 0.
            PaymentApplication.objects.create(
                payment=payment, invoice=inv, amount_applied=applied
            )
            remaining -= applied
    return payment
