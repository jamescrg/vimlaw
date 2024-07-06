import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.models import TimeEntry
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
    exclude_keys = {"_state", "id", "matter_id"}

    entry_data = {
        key: value for key, value in entry.__dict__.items() if key not in exclude_keys
    }
    entry_data["matter"] = entry.matter_id

    entry_data = {k: v if v is not None else "" for k, v in entry_data.items()}

    return entry_data
