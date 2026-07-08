"""The single trust-available authority (apps.trust.available).

Trust available is client-level: a client's pooled trust minus ALL their matters'
obligations, computed on the PENDING balance (unconfirmed deposits count). A
matter's available is simply its client's.
"""

from decimal import Decimal

import pytest

from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter, PracticeArea
from apps.trust.available import client_trust_available, trust_available_by_client
from apps.trust.models import Transaction

pytestmark = pytest.mark.django_db


def _matter(user, client, name):
    pa, _ = PracticeArea.objects.get_or_create(
        name="General", defaults={"is_active": True}
    )
    return Matter.objects.create(
        user=user, name=name, status="Open", client=client, practice_area=pa
    )


def _unbilled_time(user, matter, hours, rate):
    return TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Work",
        hours=Decimal(hours),
        rate=rate,
        comp=False,
        entered=False,
        invoice=None,
    )


def test_available_pools_all_matters_and_uses_pending(user, contact):
    # An UNCONFIRMED $1000 deposit — only counts if we use the pending balance.
    Transaction.objects.create(
        contact=contact,
        date="2024-01-01",
        type="Deposit",
        amount=Decimal("1000.00"),
        confirmed=False,
    )
    m1 = _matter(user, contact, "Matter One")
    m2 = _matter(user, contact, "Matter Two")
    _unbilled_time(user, m1, "1.0", 200)  # $200 unbilled on m1
    _unbilled_time(user, m2, "1.0", 300)  # $300 unbilled on m2

    # Pooled: 1000 (pending) − 0 owed − 500 unbilled across BOTH matters. A
    # per-matter view would wrongly show 800 / 700; a confirmed-only view -500.
    assert client_trust_available(contact.id) == Decimal("500.00")
    assert trust_available_by_client([contact.id])[contact.id] == Decimal("500.00")


def test_no_client_is_zero():
    assert client_trust_available(None) == Decimal("0")
