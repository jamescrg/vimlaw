"""The 'pending settlement' flag for provisional (unsettled ACH) online payments:
Invoice.has_pending_payment + the Payments-tab and invoice-detail badges."""

from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.payments.models import Payment

pytestmark = pytest.mark.django_db


def _apply_pending(matter, invoice):
    pay = Payment.objects.create(
        matter=matter,
        date="2024-01-01",
        amount=Decimal("1000.00"),
        payment_method="ACH",
        detail="Online payment · confido",
        processor="confido",
        processor_txn_id="txn_pending_1",
        processor_status="pending",
    )
    PaymentApplication.objects.create(
        payment=pay, invoice=invoice, amount_applied=Decimal("1000.00")
    )
    return pay


def test_invoice_has_pending_payment_property(sent_invoice, matter):
    pay = _apply_pending(matter, sent_invoice)
    assert sent_invoice.has_pending_payment is True
    # Once it settles, the flag clears.
    pay.processor_status = "succeeded"
    pay.save(update_fields=["processor_status"])
    assert sent_invoice.has_pending_payment is False


def test_payments_row_badge(sent_invoice, matter):
    pay = _apply_pending(matter, sent_invoice)
    html = render_to_string("invoicing/payments/row.html", {"payment": pay})
    assert "badge-yellow" in html and ">Pending</span>" in html
    # Settled -> no badge.
    pay.processor_status = "succeeded"
    pay.save(update_fields=["processor_status"])
    html2 = render_to_string("invoicing/payments/row.html", {"payment": pay})
    assert "badge-yellow" not in html2


def test_invoice_detail_status_badge(sent_invoice, matter):
    _apply_pending(matter, sent_invoice)
    sent_invoice.refresh_from_db()  # auto-PAID after full application
    html = render_to_string(
        "invoicing/invoices/status.html",
        {"invoice": sent_invoice, "view": "detail"},
    )
    assert "Pending settlement" in html
    # A non-detail view must NOT show the badge (and the guard short-circuits so
    # the has_pending_payment query never runs on list rows).
    html_list = render_to_string(
        "invoicing/invoices/status.html",
        {"invoice": sent_invoice, "view": "list"},
    )
    assert "Pending settlement" not in html_list
