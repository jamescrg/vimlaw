import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.matters.models import (
    Fact,
    Matter,
    Proceeding,
    Relationship,
    Role,
    SettlementEntry,
)


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
def folder(user):
    folder = Folder.objects.create(
        user=user,
        page="contacts",
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
def matter(user, contact):
    matter = Matter.objects.create(
        user_id=user.id,
        name="Sample Test Matter",
        description="Awaiting response from OC",
        status="Open",
        date_start="2020-08-07",
        date_end="2022-08-07",
        firm="Test Firm",
        firm_file_no="123",
        ref_no="125",
        practice_area="General",
        hourly_rate=300,
        firm_rate=300,
        client=contact,
    )
    return matter


@pytest.fixture
def matter_data(matter, contact):
    exclude_keys = {"_state", "id"}
    matter_data = {
        key: value for key, value in matter.__dict__.items() if key not in exclude_keys
    }

    matter_data["client"] = contact

    return matter_data


@pytest.fixture
def role():
    role = Role.objects.create(
        name="Client",
    )
    role.save()
    return role


@pytest.fixture
def relationship(matter, contact, role):
    rel = Relationship.objects.create(
        matter=matter,
        contact=contact,
        role=role,
    )
    rel.save()
    return rel


@pytest.fixture
def proceeding(user, matter):
    proceeding = Proceeding.objects.create(
        user_id=user.id,
        matter=matter,
        date_filed="2020-08-07",
        forum="Fulton Superior",
        case_number="20CV141360",
        status="Concluded",
    )
    proceeding.save()
    return proceeding


@pytest.fixture
def proceeding_data(proceeding):
    proceeding_data = proceeding.__dict__
    keys = "_state id".split()
    for key in keys:
        del proceeding_data[key]
    return proceeding_data


@pytest.fixture
def entry(user, matter):
    entry = SettlementEntry.objects.create(
        user_id=user.id,
        matter=matter,
        date="2020-08-07",
        medium="Email",
        type="Demand",
        amount="10000",
        notes="With full release",
    )
    entry.save()
    return entry


@pytest.fixture
def entry_data(entry):
    entry_data = entry.__dict__
    keys = "_state id".split()
    for key in keys:
        del entry_data[key]
    return entry_data


@pytest.fixture
def fact(user, matter):
    fact = Fact.objects.create(
        user_id=user.id,
        matter=matter,
        date="2020-08-07",
        description="Email to OC",
        citation="Evidence",
        emphasis="Yes",
    )
    return fact


@pytest.fixture
def fact_data(fact):
    exclude_keys = {"_state", "id"}
    fact_data = {
        key: value for key, value in fact.__dict__.items() if key not in exclude_keys
    }
    return fact_data
