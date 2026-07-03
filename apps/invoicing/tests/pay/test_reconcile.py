"""Tests for the settlement/return reconciliation path.

The critical, previously-untested behaviour: an accepted ACH charge that later
**returns** must be unapplied, the invoice reverted from PAID to SENT, the
phantom Payment removed, and staff emailed.

We drive a charge through the FakeProcessor (so its txn lives in the registry),
record it with ``record_payment``, then feed a webhook body to
``reconcile_webhook``. The fake's webhook parser honours a ``status`` in the body
and reports it back as the confirmed status (mirroring "re-fetch to confirm").
"""

import json

import pytest

from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.pay.balance import record_trust_deposit
from apps.invoicing.pay.reconcile import reconcile_webhook
from apps.invoicing.pay.recording import record_payment
from apps.invoicing.payments.models import Payment
from apps.invoicing.processors import BANK, CARD, get_processor
from apps.trust.models import Transaction

pytestmark = pytest.mark.django_db


def _charge_and_record(invoice, *, token, method):
    """Charge via the fake processor (populating its registry) and record the
    resulting Payment applied to ``invoice``. Returns (payment, result)."""
    processor = get_processor()
    config = processor.client_config(invoice)
    result = processor.charge(
        token=token,
        amount_cents=config.amount_cents,
        reference=config.reference,
        method=method,
    )
    payment = record_payment(invoice, result)
    return payment, result


def _charge_and_record_trust(contact, *, token, method):
    """Charge via the fake processor and record the result as a trust-ledger
    Deposit for ``contact``. Returns (deposit, result)."""
    processor = get_processor()
    result = processor.charge(
        token=token,
        amount_cents=25000,
        reference="Trust deposit · test",
        method=method,
    )
    deposit = record_trust_deposit(contact, result)
    return deposit, result


def _webhook_body(txn_id, status=None, settled=False):
    body = {"transaction_id": txn_id}
    if status is not None:
        body["status"] = status
    if settled:
        body["settled"] = True
    return json.dumps(body)


# ---------------------------------------------------------------------------
# record_payment
# ---------------------------------------------------------------------------
class TestRecordPayment:
    def test_records_and_applies(self, sent_invoice):
        payment, result = _charge_and_record(sent_invoice, token="fake-ok", method=CARD)
        assert payment is not None
        assert PaymentApplication.objects.filter(
            payment=payment, invoice=sent_invoice
        ).exists()
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"

    def test_idempotent_on_same_transaction(self, sent_invoice):
        payment, result = _charge_and_record(sent_invoice, token="fake-ok", method=CARD)
        again = record_payment(sent_invoice, result)
        assert again.pk == payment.pk
        assert Payment.objects.filter(processor="fake").count() == 1

    def test_returns_none_without_matter(self, user):
        """Payment requires a matter; a matter-less invoice cannot be recorded."""
        invoice = Invoice.objects.create(
            created_by=user,
            matter=None,
            date_limit="2024-12-31",
            date_issued="2024-12-01",
            status="SENT",
        )
        processor = get_processor()
        result = processor.charge(
            token="fake-ok",
            amount_cents=10000,
            reference="invoice:x",
            method=CARD,
        )
        assert record_payment(invoice, result) is None


# ---------------------------------------------------------------------------
# reconcile_webhook — the ACH return reversal
# ---------------------------------------------------------------------------
class TestReversal:
    def test_returned_event_reverses_payment(self, sent_invoice, settings, mailoutbox):
        settings.ADMINS = [("Admin", "admin@example.test")]

        payment, result = _charge_and_record(
            sent_invoice, token="fake-ach-return", method=BANK
        )
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"  # provisional

        reconcile_webhook("fake", _webhook_body(result.transaction_id, "returned"))

        # Payment + application removed.
        assert not Payment.objects.filter(pk=payment.pk).exists()
        assert not PaymentApplication.objects.filter(payment=payment).exists()

        # Invoice reverted to unpaid.
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"
        assert sent_invoice.amount_remaining > 0

        # Staff notified.
        assert len(mailoutbox) == 1
        assert "returned" in mailoutbox[0].subject.lower()
        assert result.transaction_id in mailoutbox[0].subject

    def test_failed_event_also_reverses(self, sent_invoice, settings, mailoutbox):
        settings.ADMINS = [("Admin", "admin@example.test")]
        payment, result = _charge_and_record(
            sent_invoice, token="fake-ach-fail", method=BANK
        )
        reconcile_webhook("fake", _webhook_body(result.transaction_id, "failed"))

        assert not Payment.objects.filter(pk=payment.pk).exists()
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"
        assert len(mailoutbox) == 1


# ---------------------------------------------------------------------------
# reconcile_webhook — non-reversing + idempotency + safety
# ---------------------------------------------------------------------------
class TestNonReversingAndIdempotent:
    def test_pending_to_succeeded_updates_status_without_unapplying(
        self, sent_invoice, mailoutbox
    ):
        payment, result = _charge_and_record(sent_invoice, token="fake-ok", method=BANK)
        assert payment.processor_status == "pending"

        reconcile_webhook("fake", _webhook_body(result.transaction_id, "succeeded"))

        payment.refresh_from_db()
        assert payment.processor_status == "succeeded"
        # Still applied; invoice still paid; no reversal email.
        assert PaymentApplication.objects.filter(payment=payment).exists()
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"
        assert len(mailoutbox) == 0

    def test_idempotent_redelivery_is_noop(self, sent_invoice, mailoutbox):
        payment, result = _charge_and_record(sent_invoice, token="fake-ok", method=CARD)
        assert payment.processor_status == "succeeded"

        # Same status re-delivered — nothing changes, no email.
        reconcile_webhook("fake", _webhook_body(result.transaction_id, "succeeded"))

        assert Payment.objects.filter(pk=payment.pk).exists()
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"
        assert len(mailoutbox) == 0

    def test_event_for_already_reversed_payment_is_noop(
        self, sent_invoice, settings, mailoutbox
    ):
        settings.ADMINS = [("Admin", "admin@example.test")]
        payment, result = _charge_and_record(
            sent_invoice, token="fake-ach-return", method=BANK
        )
        # First return reverses it (1 email).
        reconcile_webhook("fake", _webhook_body(result.transaction_id, "returned"))
        assert not Payment.objects.filter(pk=payment.pk).exists()
        assert len(mailoutbox) == 1

        # A duplicate return for the now-removed payment is a safe no-op.
        reconcile_webhook("fake", _webhook_body(result.transaction_id, "returned"))
        assert len(mailoutbox) == 1

    def test_event_for_unknown_transaction_is_safe(self, mailoutbox):
        """A webhook for a transaction we never recorded (and isn't even in the
        registry) is swallowed without error and changes nothing."""
        reconcile_webhook("fake", _webhook_body("fake_card_doesnotexist", "returned"))
        assert len(mailoutbox) == 0

    def test_unknown_processor_is_ignored(self, mailoutbox):
        reconcile_webhook("nope", _webhook_body("whatever", "returned"))
        assert len(mailoutbox) == 0


# ---------------------------------------------------------------------------
# reconcile_webhook — trust deposits (a trust.Transaction, not a Payment)
# ---------------------------------------------------------------------------
class TestTrustReconciliation:
    def test_ach_settlement_confirms_deposit(self, contact, mailoutbox):
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ok", method=BANK
        )
        assert deposit.processor_status == "pending"
        assert deposit.confirmed is False

        # ACH settles = deposited into the bank (status succeeded + settled).
        reconcile_webhook(
            "fake", _webhook_body(result.transaction_id, "succeeded", settled=True)
        )

        deposit.refresh_from_db()
        assert deposit.processor_status == "succeeded"
        assert deposit.confirmed is True  # tracks the bank
        assert Transaction.objects.filter(pk=deposit.pk).exists()
        assert len(mailoutbox) == 0

    def test_card_deposit_confirms_even_though_status_unchanged(self, contact):
        """A card records already 'succeeded' (captured) but unconfirmed; its later
        bank deposit confirms it even though the normalized status doesn't move."""
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ok", method=CARD
        )
        assert deposit.processor_status == "succeeded"
        assert deposit.confirmed is False

        reconcile_webhook("fake", _webhook_body(result.transaction_id, settled=True))

        deposit.refresh_from_db()
        assert deposit.confirmed is True

    def test_status_change_without_deposit_does_not_confirm(self, contact):
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ok", method=BANK
        )
        # A status advance that isn't a bank deposit (no `settled`) must not confirm.
        reconcile_webhook("fake", _webhook_body(result.transaction_id, "succeeded"))
        deposit.refresh_from_db()
        assert deposit.processor_status == "succeeded"
        assert deposit.confirmed is False

    def test_returned_unconfirmed_deposit_is_dropped_and_emails(
        self, contact, settings, mailoutbox
    ):
        settings.ADMINS = [("Admin", "admin@example.test")]
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ach-return", method=BANK
        )
        assert deposit.confirmed is False

        reconcile_webhook("fake", _webhook_body(result.transaction_id, "returned"))

        # Provisional deposit removed from the client's pending trust balance.
        assert not Transaction.objects.filter(pk=deposit.pk).exists()
        assert len(mailoutbox) == 1
        assert "trust deposit" in mailoutbox[0].subject.lower()
        assert result.transaction_id in mailoutbox[0].subject

    def test_returned_confirmed_deposit_is_flagged_not_deleted(
        self, contact, settings, mailoutbox
    ):
        """A return after the firm confirmed the deposit is a trust shortfall: we
        don't silently mutate the confirmed ledger — flag it for manual handling."""
        settings.ADMINS = [("Admin", "admin@example.test")]
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ach-return", method=BANK
        )
        deposit.confirmed = True
        deposit.save(update_fields=["confirmed"])

        reconcile_webhook("fake", _webhook_body(result.transaction_id, "returned"))

        deposit.refresh_from_db()
        assert deposit.processor_status == "returned"  # flagged, not deleted
        assert deposit.confirmed is True
        assert len(mailoutbox) == 1
        assert "short" in mailoutbox[0].body.lower()

    def test_idempotent_redelivery_is_noop(self, contact, mailoutbox):
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ok", method=BANK
        )
        body = _webhook_body(result.transaction_id, "succeeded", settled=True)
        reconcile_webhook("fake", body)
        reconcile_webhook("fake", body)  # re-delivered — nothing changes, no email
        deposit.refresh_from_db()
        assert deposit.confirmed is True
        assert Transaction.objects.filter(pk=deposit.pk).exists()
        assert len(mailoutbox) == 0


class TestTrustDepositRecording:
    def test_records_card_method(self, contact):
        dep, _ = _charge_and_record_trust(contact, token="fake-ok", method=CARD)
        assert dep.method == "Card"

    def test_records_ach_method(self, contact):
        dep, _ = _charge_and_record_trust(contact, token="fake-ok", method=BANK)
        assert dep.method == "ACH"

    def test_description_omits_txn_id(self, contact):
        """The txn id lives on the record (surfaced on the edit form), not baked
        into the ledger description."""
        dep, result = _charge_and_record_trust(contact, token="fake-ok", method=CARD)
        assert result.transaction_id not in dep.description
        assert dep.processor_txn_id == result.transaction_id
