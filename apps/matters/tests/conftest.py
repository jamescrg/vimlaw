import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.case.models import Fact
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.matters.models import Group, Matter, PracticeArea, Relationship, Role
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry


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
def practice_area():
    practice_area = PracticeArea.objects.create(
        name="General",
        is_active=True,
    )
    return practice_area


@pytest.fixture
def matter(user, contact, practice_area):
    matter = Matter.objects.create(
        user=user,
        name="Sample Test Matter",
        work_status="Awaiting response from OC",
        status="Open",
        date_start="2020-08-07",
        date_end="2022-08-07",
        firm="Test Firm",
        clio_matter_id="123",
        client_reference_id="125",
        practice_area=practice_area,
        client=contact,
    )
    return matter


@pytest.fixture
def matter_data(matter, contact):
    exclude_keys = {"_state", "id", "user_id", "practice_area_id"}
    matter_data = {
        key: value
        for key, value in matter.__dict__.items()
        if key not in exclude_keys and value is not None
    }

    matter_data["client"] = contact
    # Form expects practice_area as the FK id
    matter_data["practice_area"] = matter.practice_area.id
    # Ensure description has a value for form validation
    if "description" not in matter_data:
        matter_data["description"] = "Test description"

    return matter_data


@pytest.fixture
def role():
    role = Role.objects.create(
        name="Client",
    )
    role.save()
    return role


@pytest.fixture
def group():
    group = Group.objects.create(
        name="Counsel",
        order=1,
    )
    group.save()
    return group


@pytest.fixture
def relationship(matter, contact, role, group):
    rel = Relationship.objects.create(
        matter=matter,
        contact=contact,
        role=role,
        group=group,
    )
    rel.save()
    return rel


@pytest.fixture
def proceeding(user, matter):
    proceeding = Proceeding.objects.create(
        user=user,
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
    exclude_keys = {"_state", "id", "user_id", "matter_id"}
    proceeding_data = {
        key: value
        for key, value in proceeding.__dict__.items()
        if key not in exclude_keys and value is not None
    }
    return proceeding_data


@pytest.fixture
def entry(user, matter):
    from decimal import Decimal

    entry = SettlementEntry.objects.create(
        user=user,
        matter=matter,
        date="2020-08-07",
        medium="Email",
        type="Demand",
        amount=Decimal("10000.00"),
        notes="With full release",
    )
    entry.save()
    return entry


@pytest.fixture
def entry_data(entry):
    entry_data = entry.__dict__.copy()
    keys = "_state id".split()

    for key in keys:
        del entry_data[key]

    return {k: v for k, v in entry_data.items() if v is not None}


@pytest.fixture
def fact(user, matter):
    fact = Fact.objects.create(
        user=user,
        matter=matter,
        date="2020-08-07",
        description="Email to OC",
    )
    return fact


@pytest.fixture
def fact_data(fact):
    exclude_keys = {"_state", "id"}
    fact_data = {
        key: value
        for key, value in fact.__dict__.items()
        if key not in exclude_keys and value is not None
    }
    return fact_data
