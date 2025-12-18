import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.matters.models import Matter, PracticeArea
from apps.notes.models import Note


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="testuser", email="test@example.com", user_rate=100
    )
    user.set_password("testpass123")
    user.save()
    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="testuser", password="testpass123")
    client.get("/dash/")  # Set daily dash session to avoid redirect
    return client


@pytest.fixture
def folder():
    return Folder.objects.create(app="contacts", name="Test Folder")


@pytest.fixture
def contact(user, folder):
    return Contact.objects.create(
        user=user,
        folder=folder,
        name="Test Client",
        company="Test Company",
        email="client@example.com",
    )


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="Litigation", is_active=True)


@pytest.fixture
def matter(user, contact, practice_area):
    return Matter.objects.create(
        user=user,
        name="Test Matter",
        status="Open",
        date_start="2024-01-01",
        practice_area=practice_area,
        client=contact,
    )


@pytest.fixture
def note(user, matter):
    return Note.objects.create(
        author=user,
        matter=matter,
        title="Test Note",
        category="note",
        content="This is test content for the note.",
        importance=5,
    )


@pytest.fixture
def client_with_matter(client, matter):
    """Client with matter selected in session."""
    session = client.session
    session["documents_selected_matter"] = matter.id
    session["last_viewed_matter"] = matter.id
    session.save()
    client.matter = matter
    return client
