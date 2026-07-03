"""Fixtures for the online-payment flow tests.

Everything is driven through the in-process ``FakeProcessor`` (the default
``PAYMENT_PROCESSOR=fake``), so no LawPay/network access is required. The fake's
transaction registry is module-level, so we reset it (and the cache used by the
view rate-limiter) before every test for isolation.
"""

from decimal import Decimal

import pytest

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.processors import fake
from apps.matters.models import Matter, PracticeArea


@pytest.fixture(autouse=True)
def _reset_fake_processor(settings):
    """Pin the fake processor (so a dev .env with PAYMENT_PROCESSOR=stripe/lawpay
    doesn't leak in and hit the network) and clear its process-local registry and
    the rate-limit cache so tests don't leak state or rate-limit counters."""
    from django.core.cache import cache

    settings.PAYMENT_PROCESSOR = "fake"
    fake.reset()
    cache.clear()
    yield
    fake.reset()
    cache.clear()


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="testuser@example.com", user_rate=100
    )
    user.set_password("clawboy")
    user.save()
    return user


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def contact(user):
    """A client contact, for trust-deposit tests."""
    from apps.contacts.models import Contact

    return Contact.objects.create(user=user, name="Trust Client Co")


@pytest.fixture
def matter(practice_area):
    return Matter.objects.create(
        name="Pay Test Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
    )


@pytest.fixture
def sent_invoice(user, matter):
    """A SENT invoice worth $1000 (2h @ $500/hr) with a matter attached."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Billable work",
        hours=Decimal("2.0"),
        rate=500,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice


@pytest.fixture
def paid_invoice(user, matter):
    """A PAID invoice with no allocations (legacy rule => amount_remaining 0)."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="PAID",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Billable work",
        hours=Decimal("2.0"),
        rate=500,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice
