import pytest

from django.test import Client

from apps.accounts.models import CustomUser
from apps.events.models import Event
from apps.matters.models import Matter


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
def event(user, matter):
    event = Event.objects.create(
        user_id=user.id,
        matter=matter,
        date="2022-12-28",
        party="Client",
        description="File Answer",
        status="Pending",
    )
    event.save()
    return event


@pytest.fixture
def event_data(event):
    event_data = event.__dict__
    keys = "_state id google_id".split()
    for key in keys:
        del event_data[key]
    event_data["matter"] = event_data["matter_id"]
    return event_data


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
