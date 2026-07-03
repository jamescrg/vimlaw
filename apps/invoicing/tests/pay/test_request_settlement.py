"""PaymentRequest.settlement_pending drives the requests-table "Pending" badge.

A paid request is provisional while its fulfilling charge is still an unsettled
ACH — an operating request fulfils via ``payment``, a trust deposit via
``trust_transaction``. Regression: the property used to only inspect ``payment``,
so trust deposits never showed the badge even while pending.
"""

from decimal import Decimal

import pytest

from apps.invoicing.payments.models import Payment
from apps.invoicing.requests.models import PaymentRequest
from apps.trust.models import Transaction

pytestmark = pytest.mark.django_db


def _trust_request(contact, txn_status):
    txn = Transaction.objects.create(
        contact=contact,
        date="2024-01-01",
        type="Deposit",
        amount=Decimal("250.00"),
        confirmed=False,
        entered=False,
        processor="confido",
        processor_txn_id=f"trust-{txn_status}",
        processor_status=txn_status,
    )
    return PaymentRequest.objects.create(
        account="trust",
        client=contact,
        amount_requested=Decimal("250.00"),
        recipient_email="client@example.test",
        status="PAID",
        trust_transaction=txn,
    )


def _operating_request(matter, txn_status):
    pay = Payment.objects.create(
        matter=matter,
        date="2024-01-01",
        amount=Decimal("100.00"),
        payment_method="ACH",
        processor="confido",
        processor_txn_id=f"op-{txn_status}",
        processor_status=txn_status,
    )
    return PaymentRequest.objects.create(
        account="operating",
        matter=matter,
        amount_requested=Decimal("100.00"),
        recipient_email="client@example.test",
        status="PAID",
        payment=pay,
    )


def test_trust_request_pending_while_deposit_unsettled(contact):
    assert _trust_request(contact, "pending").settlement_pending is True


def test_trust_request_settled_shows_no_badge(contact):
    assert _trust_request(contact, "succeeded").settlement_pending is False


def test_operating_request_pending_while_payment_unsettled(matter):
    assert _operating_request(matter, "pending").settlement_pending is True


def test_operating_request_settled_shows_no_badge(matter):
    assert _operating_request(matter, "succeeded").settlement_pending is False


def test_sent_request_is_never_pending(contact):
    req = PaymentRequest.objects.create(
        account="trust",
        client=contact,
        amount_requested=Decimal("250.00"),
        recipient_email="client@example.test",
        status="SENT",
    )
    assert req.settlement_pending is False
