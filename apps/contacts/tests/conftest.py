import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact, RelationshipType
from apps.folders.models import Folder
from apps.intakes.models import Intake
from apps.matters.models import Group, Matter, PracticeArea, Relationship, Role


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="testuser@example.com", user_rate=100
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
        phone1="406.555.1234",
        phone1_label="Work",
        phone2="123.456.2222",
        phone2_label="Mobile",
        phone3="123.456.5555",
        phone3_label="Other",
        email="contact@example.com",
        website="example.com",
        notes="The Mahatma",
    )
    contact.save()

    return contact


@pytest.fixture
def contact_data(contact):
    exclude_keys = {"_state", "id", "google_id", "map", "intake_id"}
    contact_data = {
        key: value for key, value in contact.__dict__.items() if key not in exclude_keys
    }
    # Replace None values with empty strings for form submission
    contact_data = {k: v if v is not None else "" for k, v in contact_data.items()}
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
def group():
    group = Group.objects.create(
        name="Client",
        order=1,
    )
    group.save()
    return group


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
        email="contact@example.com",
    )
    intake.save()
    return intake


@pytest.fixture
def contact_beta(user, folder):
    return Contact.objects.create(
        user=user,
        folder=folder,
        name="Kasturba Gandhi",
        email="kasturba@example.com",
    )


@pytest.fixture
def contact_gamma(user, folder):
    return Contact.objects.create(
        user=user,
        folder=folder,
        name="Jawaharlal Nehru",
        email="nehru@example.com",
    )


@pytest.fixture
def symmetric_type():
    # The seed migration already provides this type; reuse it.
    return RelationshipType.objects.get_or_create(label="Spouse of")[0]


@pytest.fixture
def asymmetric_type():
    return RelationshipType.objects.get_or_create(
        label="Employer of", defaults={"inverse_label": "Employee of"}
    )[0]
