from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
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
    client.get("/dash/")
    return client


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def matter(practice_area):
    return Matter.objects.create(
        name="Credit Test Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
    )


@pytest.fixture
def credit(matter):
    return Credit.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("1000.00"),
        detail="Test credit",
    )


@pytest.fixture
def credit_data(credit):
    return {
        "matter": credit.matter.id,
        "date": "2024-12-15",
        "amount": "1000.00",
        "detail": "Test credit",
    }


@pytest.fixture
def sent_invoice(user, matter):
    """A SENT invoice with $1000 total (2h @ $500/hr)."""
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
def sent_invoice_small(user, matter):
    """A second SENT invoice with $200 total (1h @ $200/hr)."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-11-30",
        date_issued="2024-11-01",
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-02",
        actions="Small task",
        hours=Decimal("1.0"),
        rate=200,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice
