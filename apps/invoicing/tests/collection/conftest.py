from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter, PracticeArea


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="ollie@gmail.com", user_rate=100, is_staff=True
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
def folder():
    return Folder.objects.create(app="contacts", name="Clients")


@pytest.fixture
def contact(user, folder):
    return Contact.objects.create(user=user, folder=folder, name="Test Client")


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def matter(practice_area, contact):
    return Matter.objects.create(
        name="Collection Test Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
        client=contact,
    )


@pytest.fixture
def sent_invoice(user, matter):
    """A SENT invoice with $1000 total."""
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
def payment_partial(matter):
    return Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("400.00"),
        payment_method="CHECK",
    )


@pytest.fixture
def credit_small(matter):
    return Credit.objects.create(
        matter=matter,
        date="2024-12-20",
        amount=Decimal("100.00"),
        detail="Small credit",
    )
