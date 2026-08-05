import pytest
from django.core.files.base import ContentFile
from django.test import Client

from apps.accounts.models import CustomUser
from apps.case.ai.models import Conversation
from apps.drafts.models import DraftSession, DraftVersion
from apps.matters.models import Matter


@pytest.fixture
def user(db):
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
def matter(db):
    return Matter.objects.create(
        name="Smith v Jones", status="Open", drive_folder="Smith v. Jones"
    )


@pytest.fixture
def session(matter, user):
    """A drafting session with a version 0 carrying dummy blobs (no
    LibreOffice involved)."""
    conversation = Conversation.objects.create(
        title="Draft: motion.odt", llm="claude-opus", vet_citations=False, user=user
    )
    session = DraftSession.objects.create(
        matter=matter,
        conversation=conversation,
        user=user,
        drive_file_id="file1",
        name="motion.odt",
        drive_modified="2026-08-01T12:00:00.000Z",
    )
    version = DraftVersion(
        session=session, seq=0, facsimile="# MOTION\n\nSome text.", edits=[]
    )
    version.odt_file.save("v0.odt", ContentFile(b"fake-odt"), save=False)
    version.pdf_file.save("v0.pdf", ContentFile(b"%PDF-fake"), save=False)
    version.save()
    return session
