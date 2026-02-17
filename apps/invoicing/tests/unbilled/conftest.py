from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.folders.models import Folder
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
        name="Unbilled Test Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
        client=contact,
    )


@pytest.fixture
def unbilled_time(user, matter):
    """Unbilled time entry: 2h @ $300/hr = $600 fee."""
    return TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-12-01",
        actions="Unbilled work",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
        invoice=None,
    )


@pytest.fixture
def unbilled_expense(user, matter):
    """Unbilled expense of $150."""
    return ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-12-01",
        category="Filing Fee",
        description="Court filing",
        amount=Decimal("150.00"),
        comp=False,
        entered=False,
        invoice=None,
    )
