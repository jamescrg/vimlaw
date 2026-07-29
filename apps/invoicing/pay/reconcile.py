"""Reconcile processor webhook events against recorded charges.

Runs out-of-band (via Django-Q `async_task`, or inline as a fallback). The
processor's `verify_and_parse_webhook` does NOT trust the posted body — it
re-fetches the transaction from the API and reports the authoritative status —
so this module acts on a confirmed `WebhookEvent`.

An event settles or reverses whichever row carries its processor txn id: an
operating `Payment` (applied to invoices) or a trust-ledger deposit
`Transaction`. The critical case is ACH: a charge that looked accepted can
**return** or **fail** days later —
  - operating: unapply the payment (reverting the invoice to unpaid via the
    existing `PaymentApplication.delete()` hook) and drop the phantom payment;
  - trust: drop the still-unconfirmed deposit (its simple_history row keeps the
    audit trail), or — if the firm already confirmed it — flag it for manual
    reconciliation rather than silently mutating the confirmed ledger.
Either way, staff are emailed.

Webhooks are the normal driver, but a delivery that never arrives would leave
an ACH row `pending` (and a trust deposit unconfirmed) forever. `poll_pending`
is the backstop: it re-fetches every in-flight row from the processor's API
(the same authoritative fetch webhook verification uses) and applies the result
through the same rules. Run it via `manage.py reconcile_pending`, or point a
django_q Schedule at this function directly.
"""

import logging
from types import SimpleNamespace

from django.core.mail import mail_admins
from django.db.models import Q

from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.invoicing.processors import (
    PENDING,
    REVERSED_STATUSES,
    PaymentError,
    WebhookEvent,
    get_processor,
)
from apps.trust.models import Transaction

logger = logging.getLogger(__name__)


def reconcile_webhook(processor_name, body, signature=""):
    """Verify and apply a single webhook delivery. Safe to call from a task.

    `signature` carries the processor's signature header (e.g. Stripe-Signature);
    processors that don't sign (LawPay re-fetches instead) ignore it.
    """
    try:
        processor = get_processor(processor_name)
    except PaymentError:
        logger.warning("Webhook for unknown processor %r ignored", processor_name)
        return
    raw = body.encode() if isinstance(body, str) else body
    try:
        event = processor.verify_and_parse_webhook(
            SimpleNamespace(body=raw, signature=signature)
        )
    except PaymentError as exc:
        logger.warning("Unverifiable %s webhook ignored: %s", processor_name, exc)
        return
    _apply_event(event)


def poll_pending(*, dry_run=False):
    """Re-fetch every in-flight online payment row from its processor and apply
    the authoritative result through the same rules as a webhook delivery.
    Idempotent; safe to run on a schedule.

    Polled: operating Payments still `pending` (ACH awaiting settlement) and
    trust deposits still `pending` or not yet confirmed (a card deposit stays
    succeeded/unconfirmed until its later bank deposit).

    Returns one human-readable line per row polled (which is also what a
    django_q Schedule stores as the task result).
    """
    lines = []
    for row in _pending_rows():
        kind = "Payment" if isinstance(row, Payment) else "Trust deposit"
        label = (
            f"{kind} #{row.pk} (${row.amount}, {row.processor} {row.processor_txn_id})"
        )
        try:
            result = get_processor(row.processor).fetch_transaction(
                row.processor_txn_id
            )
        except PaymentError as exc:
            lines.append(f"{label}: fetch failed: {exc}")
            continue
        outcome = f"{row.processor_status or '?'} -> {result.status}"
        if result.settled:
            outcome += ", settled"
        if dry_run:
            lines.append(f"{label}: {outcome} (dry run, not applied)")
            continue
        _apply_event(_event_from_result(result))
        lines.append(f"{label}: {outcome}")
    return lines


def _pending_rows():
    """Online rows the processor may know more about than we do."""
    payments = Payment.objects.exclude(processor_txn_id="").filter(
        processor_status=PENDING
    )
    deposits = Transaction.objects.exclude(processor_txn_id="").filter(
        Q(processor_status=PENDING) | Q(confirmed=False)
    )
    return [*payments, *deposits]


def _event_from_result(result):
    """Dress a fetched transaction as the webhook event it never sent, so the
    poll rides the exact settle/reverse/confirm path deliveries do."""
    return WebhookEvent(
        processor=result.processor,
        event_id=f"poll-{result.transaction_id}",
        transaction_id=result.transaction_id,
        status=result.status,
        amount_cents=result.amount_cents,
        raw=result.raw,
        settled=result.settled,
    )


def _apply_event(event):
    """Route the event to the row it settles/reverses — an operating Payment or a
    trust deposit Transaction (both carry the processor txn id). An id we never
    recorded (or already reversed) is a safe no-op."""
    payment = Payment.objects.filter(
        processor=event.processor, processor_txn_id=event.transaction_id
    ).first()
    if payment is not None:
        _settle_or_reverse(payment, event, _reverse_payment)
        return
    deposit = Transaction.objects.filter(
        processor=event.processor, processor_txn_id=event.transaction_id
    ).first()
    if deposit is not None:
        _apply_to_deposit(deposit, event)


def _settle_or_reverse(row, event, reverse):
    """Shared dispatch for a Payment or a trust Transaction: an idempotent status
    update on settle, delegate to `reverse` on a return/failure/void."""
    if row.processor_status == event.status:
        return  # idempotent: webhook re-delivery, already in this state
    if event.status in REVERSED_STATUSES:
        reverse(row, event)
    else:
        row.processor_status = event.status
        row.save(update_fields=["processor_status"])


def _apply_to_deposit(deposit, event):
    """A trust deposit's settlement/return. Like the payment path, but also flips
    `confirmed` once the funds have actually deposited into the trust bank account
    (`event.settled`) — so the confirmed balance tracks the bank. For a card that's
    its later deposit, not the capture; the confirm can therefore land while the
    normalized status is unchanged (still 'succeeded')."""
    if event.status in REVERSED_STATUSES:
        _reverse_deposit(deposit, event)
        return
    changed = []
    if deposit.processor_status != event.status:
        deposit.processor_status = event.status
        changed.append("processor_status")
    if event.settled and not deposit.confirmed:
        deposit.confirmed = True
        changed.append("confirmed")
    if changed:
        deposit.save(update_fields=changed)


def _reverse_payment(payment, event):
    """An accepted operating charge fell through (ACH return / NSF / void)."""
    invoice_ids = list(payment.applications.values_list("invoice_id", flat=True))
    # Delete each application individually so PaymentApplication.delete() runs
    # (records history; a cascade delete would skip the hook).
    for application in list(payment.applications.all()):
        application.delete()
    detail = payment.detail
    payment.delete()

    # The delete hook leaves an invoice PAID when its *last* allocation is removed
    # (a legacy amount_remaining rule counts PAID + no-allocations as fully paid).
    # Explicitly revert any such invoice so a returned payment shows as unpaid —
    # but leave PAID any invoice still fully covered by other allocations.
    for inv_id in invoice_ids:
        inv = Invoice.objects.filter(pk=inv_id).first()
        if inv is None or inv.status != "PAID":
            continue
        has_alloc = inv.applications.exists() or inv.credit_applications.exists()
        if not has_alloc or inv.amount_remaining > 0:
            inv.status = "SENT"
            inv.save(update_fields=["status"])

    mail_admins(
        subject=f"Online payment {event.status}: {event.transaction_id}",
        message=(
            f"A previously-accepted online payment has {event.status}.\n\n"
            f"{detail}\n"
            f"Affected invoice id(s): {invoice_ids}\n\n"
            "The invoice has been reverted to unpaid. Please follow up with the "
            "client."
        ),
        fail_silently=True,
    )
    logger.warning(
        "Reversed online payment %s (%s); invoices %s reverted",
        event.transaction_id,
        event.status,
        invoice_ids,
    )


def _reverse_deposit(deposit, event):
    """An accepted trust deposit fell through (ACH return / NSF / void).

    An unconfirmed deposit never counted as cleared funds, so drop it (its
    simple_history row keeps the audit trail) — mirroring the phantom-payment
    removal. A deposit the firm already CONFIRMED is a trust shortfall: don't
    silently mutate the confirmed ledger — flag its status and leave it for staff
    to reconcile by hand. Either way, email staff."""
    contact = deposit.contact
    description = deposit.description
    amount = deposit.amount
    if deposit.confirmed:
        deposit.processor_status = event.status
        deposit.save(update_fields=["processor_status"])
        outcome = (
            "This deposit was already CONFIRMED, so the confirmed trust balance "
            "may now be short — reconcile it by hand."
        )
    else:
        deposit.delete()
        outcome = (
            "It was unconfirmed and has been removed from the client's pending "
            "trust balance."
        )

    mail_admins(
        subject=f"Trust deposit {event.status}: {event.transaction_id}",
        message=(
            f"A previously-accepted online trust deposit has {event.status}.\n\n"
            f"Client: {contact}\n"
            f"{description}\n"
            f"Amount: ${amount}\n\n"
            f"{outcome} Please follow up with the client."
        ),
        fail_silently=True,
    )
    logger.warning(
        "Reversed online trust deposit %s (%s) for contact %s",
        event.transaction_id,
        event.status,
        getattr(contact, "id", None),
    )
