import pytest

from django.test import Client

from accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.intakes.models import Intake
from apps.intakes.models import Note


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
def contact(user, folder):
    contact = Contact.objects.create(
        user=user,
        folder=folder,
        name="Mohandas Gandhi",
        company="Gandhi, PC",
        address="225 Paper Street, Porbandar, India",
        phone1="406.363.1234",
        phone1_label="Work",
        phone2="123.456.2222",
        phone2_label="Mobile",
        phone3="123.456.5555",
        phone3_label="Other",
        email="gandhi@gandhi.com",
        website="gandhi.com",
        notes="The Mahatma",
    )
    contact.save()
    return contact


@pytest.fixture
def intake():
    intake = Intake.objects.create(
        date="2020-01-01",
        name="Mohandas Gandhi",
        address="225 Paper Street, Porbandar, India",
        phone="123.456.7890",
        email="gandhi@gandhi.com",
        practice_area="General",
        source="Internet",
    )
    intake.save()
    return intake


@pytest.fixture
def intake_data(intake):
    intake_data = intake.__dict__
    keys = "_state id".split()
    for key in keys:
        del intake_data[key]
    return intake_data


@pytest.fixture
def note(user, intake):
    note = Note.objects.create(
        user=user,
        intake=intake,
        date="2022-12-28",
        time="00:00",
        type="General",
        details="",
    )
    note.save()
    return note


@pytest.fixture
def note_data(note):
    note_data = note.__dict__
    keys = "_state id".split()
    for key in keys:
        del note_data[key]
    return note_data
