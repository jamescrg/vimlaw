import pytest

from django.test import Client

from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from apps.activity.models import TimeEntry


@pytest.fixture
def user():
    user = CustomUser.objects.create_user("Ollie", "ollie@gmail.com", "clawboy")
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
    matter.save()
    return matter


@pytest.fixture
def entry(user, matter):
    entry = TimeEntry.objects.create(
        user_id=user.id,
        matter=matter,
        date="2020-01-07",
        actions="Call with client",
        hours=0.2,
        contractor_rate=0,
        firm_rate=300,
        comp=0,
        entered=0,
    )
    entry.save()
    return entry


@pytest.fixture
def entry_data(entry):
    entry_data = entry.__dict__
    keys = "_state id".split()
    for key in keys:
        del entry_data[key]
    entry_data["matter"] = entry_data["matter_id"]
    return entry_data
