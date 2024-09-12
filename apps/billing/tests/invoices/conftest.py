import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.billing.invoices.models import Invoice
from apps.matters.models import Matter


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
def matter():
    matter = Matter.objects.create(
        name="Sample Test Matter",
        description="Awaiting response from OC",
        status="Open",
        practice_area="General",
    )

    return matter


@pytest.fixture
def entry(user, matter):
    entry = TimeEntry.objects.create(
        user_id=user.id,
        matter=matter,
        date="2020-01-07",
        actions="Call with client",
        hours=0.2,
        rate=300,
        comp=0,
        entered=0,
    )
    entry.save()
    return entry


@pytest.fixture
def invoice(user, matter, entry):
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
    )

    return invoice


@pytest.fixture
def invoice_data(invoice):
    exclude_keys = {"_state", "id", "matter_id", "created_by_id"}

    invoice_data = {
        key: value for key, value in invoice.__dict__.items() if key not in exclude_keys
    }

    invoice_data["matter"] = invoice.matter_id

    return invoice_data
