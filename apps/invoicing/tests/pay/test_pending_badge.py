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


def test_invoice_payment_history_badge(sent_invoice, matter):
    """The badge lives on the specific pending payment in the invoice's Payment
    history (not next to the status)."""
    _apply_pending(matter, sent_invoice)
    html = render_to_string(
        "invoicing/invoices/detail/history-content.html", {"invoice": sent_invoice}
    )
    assert "Pending settlement" in html
    # ...and the status display no longer carries it.
    status = render_to_string(
        "invoicing/invoices/status.html",
        {"invoice": sent_invoice, "view": "detail"},
    )
    assert "Pending settlement" not in status


def test_invoices_list_annotates_and_badges_pending(sent_invoice, matter):
    """The list annotates a pending flag (no N+1) and floats a badge in the
    matter cell."""
    from apps.invoicing.invoices.get_invoice_data import (
        get_annotated_invoice_queryset,
    )

    _apply_pending(matter, sent_invoice)
    inv = get_annotated_invoice_queryset().get(id=sent_invoice.id)
    assert inv.annotated_has_pending_payment is True
    html = render_to_string(
        "invoicing/invoices/row.html", {"invoice": inv, "view": "list"}
    )
    assert "badge-flag-row" in html and ">Pending</span>" in html
