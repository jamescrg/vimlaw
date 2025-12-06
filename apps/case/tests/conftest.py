import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import CustomUser
from apps.case.models import Document, Fact, Highlight, Label
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.matters.models import Matter, PracticeArea
from apps.matters.proceedings.models import Proceeding


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
def proceeding(user, matter):
    return Proceeding.objects.create(
        user=user,
        matter=matter,
        date_filed="2024-01-15",
        forum="Superior Court",
        case_number="2024CV001",
        status="Pending",
    )


@pytest.fixture
def label(matter):
    return Label.objects.create(matter=matter, name="Important", color="red")


@pytest.fixture
def global_label():
    return Label.objects.create(matter=None, name="Global Label", color="blue")


@pytest.fixture
def pdf_file():
    """Create a minimal valid PDF file for testing."""
    pdf_content = (
        b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
        b"2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n"
        b"3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n199\n%%EOF"
    )
    return SimpleUploadedFile("test.pdf", pdf_content, content_type="application/pdf")


@pytest.fixture
def document(matter, user, pdf_file):
    # Create document first without file to get ID
    doc = Document(
        matter=matter,
        name="Test Document",
        description="A test document",
        category="Evidence",
        uploaded_by=user,
        date="2024-01-20",
        ocr_status="not_applicable",
    )
    doc.save()
    # Now save with file
    doc.file = pdf_file
    doc.save()
    return doc


@pytest.fixture
def document_data(document):
    return {
        "name": document.name,
        "description": document.description,
        "category": document.category,
        "date": str(document.date) if document.date else "",
    }


@pytest.fixture
def highlight(document, user):
    return Highlight.objects.create(
        document=document,
        slug="Test Highlight",
        text="This is highlighted text from the document.",
        page_number=1,
        paragraph_number="5",
        coordinates={"rects": [{"x1": 100, "y1": 100, "x2": 200, "y2": 120}]},
        color="yellow",
        created_by=user,
        importance=5,
    )


@pytest.fixture
def highlight_data(highlight):
    return {
        "slug": highlight.slug,
        "text": highlight.text,
        "page_number": highlight.page_number,
        "paragraph_number": highlight.paragraph_number,
        "coordinates": highlight.coordinates,
        "color": highlight.color,
    }


@pytest.fixture
def fact(user, matter):
    return Fact.objects.create(
        user=user,
        matter=matter,
        date="2024-01-25",
        description="Important event occurred",
        importance=5,
    )


@pytest.fixture
def fact_data(fact):
    return {
        "date": str(fact.date),
        "description": fact.description,
        "importance": fact.importance,
    }


@pytest.fixture
def client_with_matter(client, matter):
    """Client with matter selected in session."""
    session = client.session
    session["documents_selected_matter"] = matter.id
    session.save()
    return client
