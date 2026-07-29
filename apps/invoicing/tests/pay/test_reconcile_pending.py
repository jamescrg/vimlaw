"""Tests for the reconcile_pending missed-webhook backstop.

The webhook path (test_reconcile) covers the settle/reverse/confirm rules
themselves; these cover the polling wrapper: in-flight rows are found,
re-fetched from the processor, and pushed through those same rules without a
webhook ever arriving. Rows the processor can't know more about (manual
payments, settled cards) are left alone.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.invoicing.pay.balance import record_trust_deposit
from apps.invoicing.pay.reconcile import poll_pending
from apps.invoicing.pay.recording import record_payment
from apps.invoicing.payments.models import Payment
from apps.invoicing.processors import BANK, CARD, get_processor
from apps.trust.models import Transaction

pytestmark = pytest.mark.django_db


def _charge_and_record(invoice, *, token, method):
    processor = get_processor()
    config = processor.client_config(invoice)
    result = processor.charge(
        token=token,
        amount_cents=config.amount_cents,
        reference=config.reference,
        method=method,
    )
    return record_payment(invoice, result), result


def _charge_and_record_trust(contact, *, token, method):
    processor = get_processor()
    result = processor.charge(
        token=token,
        amount_cents=25000,
        reference="Trust deposit · test",
        method=method,
    )
    return record_trust_deposit(contact, result), result


def _run(*args):
    out = StringIO()
    call_command("reconcile_pending", *args, stdout=out)
    return out.getvalue()


class TestPayments:
    def test_settles_pending_ach_payment(self, sent_invoice):
        payment, result = _charge_and_record(sent_invoice, token="fake-ok", method=BANK)
        assert payment.processor_status == "pending"
        get_processor().simulate_deposit(result.transaction_id)

        output = _run()

        payment.refresh_from_db()
        assert payment.processor_status == "succeeded"
        assert f"Payment #{payment.pk}" in output
        assert "pending -> succeeded, settled" in output

    def test_reverses_returned_ach_payment(self, sent_invoice, settings, mailoutbox):
        settings.ADMINS = [("Admin", "admin@example.test")]
        payment, result = _charge_and_record(
            sent_invoice, token="fake-ach-return", method=BANK
        )
        get_processor().simulate_settlement(result.transaction_id)

        _run()

        assert not Payment.objects.filter(pk=payment.pk).exists()
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"
        assert len(mailoutbox) == 1
        assert "returned" in mailoutbox[0].subject.lower()

    def test_still_pending_row_is_left_pending(self, sent_invoice):
        payment, _ = _charge_and_record(sent_invoice, token="fake-ok", method=BANK)

        output = _run()

        payment.refresh_from_db()
        assert payment.processor_status == "pending"
        assert "pending -> pending" in output

    def test_settled_and_manual_rows_are_not_polled(self, sent_invoice, matter):
        _charge_and_record(sent_invoice, token="fake-ok", method=CARD)  # succeeded
        Payment.objects.create(
            matter=matter, date="2026-07-01", amount=100, payment_method="CHECK"
        )
        assert poll_pending() == []
        assert "Nothing to reconcile." in _run()

    def test_fetch_failure_is_reported_not_fatal(self, matter):
        stuck = Payment.objects.create(
            matter=matter,
            date="2026-07-01",
            amount=85,
            payment_method="ACH",
            processor="fake",
            processor_txn_id="fake_bank_gone",
            processor_status="pending",
        )
        output = _run()
        stuck.refresh_from_db()
        assert stuck.processor_status == "pending"
        assert "fetch failed" in output


class TestTrustDeposits:
    def test_settlement_confirms_ach_deposit(self, contact):
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ok", method=BANK
        )
        assert deposit.processor_status == "pending"
        assert deposit.confirmed is False
        get_processor().simulate_deposit(result.transaction_id)

        _run()

        deposit.refresh_from_db()
        assert deposit.processor_status == "succeeded"
        assert deposit.confirmed is True

    def test_deposit_confirms_card_even_though_status_unchanged(self, contact):
        deposit, result = _charge_and_record_trust(
            contact, token="fake-ok", method=CARD
        )
        assert deposit.processor_status == "succeeded"
        assert deposit.confirmed is False
        get_processor().simulate_deposit(result.transaction_id)

        _run()

        deposit.refresh_from_db()
        assert deposit.confirmed is True
        assert Transaction.objects.filter(pk=deposit.pk).exists()


class TestDryRun:
    def test_dry_run_reports_without_applying(self, sent_invoice):
        payment, result = _charge_and_record(sent_invoice, token="fake-ok", method=BANK)
        get_processor().simulate_deposit(result.transaction_id)

        output = _run("--dry-run")

        payment.refresh_from_db()
        assert payment.processor_status == "pending"
        assert "dry run, not applied" in output
        assert "pending -> succeeded" in output
