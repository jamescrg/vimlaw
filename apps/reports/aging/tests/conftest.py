from datetime import date, timedelta

import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.invoicing.invoices.models import Invoice
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
def contact_alpha(user, folder):
    return Contact.objects.create(user=user, folder=folder, name="Alpha Client")


@pytest.fixture
def contact_beta(user, folder):
    return Contact.objects.create(user=user, folder=folder, name="Beta Client")


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def matter_alpha(practice_area, contact_alpha):
    return Matter.objects.create(
        name="Alpha Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
        client=contact_alpha,
    )


@pytest.fixture
def matter_beta(practice_area, contact_beta):
    return Matter.objects.create(
        name="Beta Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
        client=contact_beta,
    )


def _create_sent_invoice(user, matter, days_old, amount_hours, rate):
    """Helper to create a SENT invoice aged a given number of days."""
    today = date.today()
    issued = today - timedelta(days=days_old)
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit=str(issued),
        date_issued=str(issued),
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date=str(issued),
        actions="Work",
        hours=amount_hours,
        rate=rate,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice
