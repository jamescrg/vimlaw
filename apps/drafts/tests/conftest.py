import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.case.ai.models import Conversation
from apps.drafts.models import DraftLink
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
def conversation(matter, user):
    return Conversation.objects.create(
        matter=matter, title="Drafting the motion", llm="gemini-pro-latest", user=user
    )


@pytest.fixture
def link(conversation):
    return DraftLink.objects.create(
        conversation=conversation,
        drive_file_id="file1",
        name="motion.odt",
        doc_text="# MOTION\n\nSome text.",
        doc_text_at=timezone.now(),
    )
