from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter, PracticeArea


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="ollie@gmail.com", user_rate=100
    )
    user.set_password("clawboy")
    user.save()
    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def matter(practice_area):
    return Matter.objects.create(
        name="Test Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
    )


@pytest.fixture
def invoice_sent(user, matter):
    """A SENT invoice with $1000 total value (from time entries)."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
    )
    # Create time entry worth $1000 (2 hours at $500/hr)
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
def payment(matter):
    """A payment of $1000."""
    return Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("1000.00"),
        payment_method="CHECK",
    )


@pytest.fixture
def payment_partial(matter):
    """A partial payment of $500."""
    return Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("500.00"),
        payment_method="CHECK",
    )


@pytest.fixture
def credit(matter):
    """A credit of $1000."""
    return Credit.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("1000.00"),
        detail="Client credit",
    )


@pytest.fixture
def credit_partial(matter):
    """A partial credit of $500."""
    return Credit.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("500.00"),
        detail="Partial credit",
    )
