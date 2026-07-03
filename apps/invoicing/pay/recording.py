"""Record an accepted online charge as a Payment applied to its invoice.

Card charges settle immediately; pending ACH charges are recorded too, so the
invoice shows paid *provisionally* — the settlement webhook later confirms it,
or a return reverses it (see `reconcile`). Reuses the existing Payment /
PaymentApplication models, so the auto-PAID behaviour comes for free.
"""

from decimal import Decimal

from django.utils import timezone

from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.payments.models import Payment
from apps.invoicing.processors import CARD


def record_payment(invoice, result):
    """Create (idempotently) a Payment for `result` and apply it to `invoice`.

    Returns the Payment, or None if it could not be recorded (no matter on the
    invoice — Payment requires one).
    """
    if not invoice.matter_id:
        return None

    existing = Payment.objects.filter(
        processor=result.processor, processor_txn_id=result.transaction_id
    ).first()
    if existing:
        return existing

    amount = Decimal(result.amount_cents) / Decimal(100)
    method = "CARD" if result.method == CARD else "ACH"
    payment = Payment.objects.create(
        matter=invoice.matter,
        date=timezone.localdate(),
        amount=amount,
        payment_method=method,
        detail=f"Online payment · {result.processor}",
        processor=result.processor,
        processor_txn_id=result.transaction_id,
        processor_status=result.status,
    )
    # Applying the full charged amount flips the invoice to PAID via
    # PaymentApplication.save()'s existing auto-PAID hook.
    PaymentApplication.objects.create(
        payment=payment, invoice=invoice, amount_applied=amount
    )
    return payment
