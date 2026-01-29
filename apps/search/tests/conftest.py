import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.intakes.models import Intake
from apps.matters.models import Matter, PracticeArea, Relationship, Role
from apps.matters.proceedings.models import Proceeding


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
    client.get("/dash/")  # Set daily dash session to avoid redirect
    return client


@pytest.fixture
def folder():
    folder = Folder.objects.create(
        app="contacts",
        name="Mahatmas",
    )
    folder.save()
    return folder


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
def contact_data(contact):
    contact_data = contact.__dict__
    keys = "_state id google_id map intake_id".split()
    for key in keys:
        del contact_data[key]
    return contact_data


@pytest.fixture
def practice_area():
    practice_area = PracticeArea.objects.create(name="General", is_active=True)
    return practice_area


@pytest.fixture
def matter(practice_area):
    matter = Matter.objects.create(
        name="Sample Test Matter",
        work_status="Awaiting response from OC",
        status="Open",
        practice_area=practice_area,
    )
    matter.save()
    return matter


@pytest.fixture
def role():
    role = Role.objects.create(
        name="Client",
    )
    role.save()
    return role


@pytest.fixture
def relationship():
    rel = Relationship.objects.create(
        name="Client",
    )
    rel.save()
    return rel


@pytest.fixture
def intake():
    intake = Intake.objects.create(
        name="Mohandas Gandhi",
        address="225 Paper Street, Porbandar, India",
        phone="123.456.7890",
        email="gandhi@gandhi.com",
    )
    intake.save()
    return intake


@pytest.fixture
def proceeding(matter):
    proceeding = Proceeding.objects.create(
        matter=matter,
        forum="District Court",
        case_number="2024-CV-12345",
        status="Ongoing",
        primary=True,
    )
    proceeding.save()
    return proceeding
