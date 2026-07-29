import copy

import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.intakes.client_forms.schema import normalize_schema
from apps.intakes.models import FormSubmission, FormTemplate, Intake, Note
from apps.matters.models import PracticeArea


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
def practice_area():
    practice_area = PracticeArea.objects.create(
        name="General",
        is_active=True,
    )
    return practice_area


@pytest.fixture
def intake(practice_area):
    intake = Intake.objects.create(
        date="2020-01-01",
        name="Mohandas Gandhi",
        address="225 Paper Street, Porbandar, India",
        phone="123.456.7890",
        email="contact@example.com",
        practice_area=practice_area,
        source="Internet",
    )
    intake.save()
    return intake


@pytest.fixture
def intake_data(intake):
    intake_data = intake.__dict__.copy()
    keys = "_state id practice_area_id".split()
    for key in keys:
        if key in intake_data:
            del intake_data[key]
    # Form expects practice_area as the FK id
    intake_data["practice_area"] = intake.practice_area.id
    # Remove None values as they can't be encoded in POST data
    intake_data = {k: v for k, v in intake_data.items() if v is not None}
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
    note_data = note.__dict__.copy()
    keys = "_state id".split()

    for key in keys:
        del note_data[key]

    return {k: v for k, v in note_data.items() if v is not None}


# --- Custom intake forms ----------------------------------------------------


@pytest.fixture
def form_template():
    """A four-question template, one of each shape the snapshot tests care
    about: free text, a heading, a dropdown, and a date."""
    return FormTemplate.objects.create(
        name="Property Dispute Questionnaire",
        description="Background on the property and the dispute.",
        intro_text="Please answer as fully as you can.",
        schema=normalize_schema(
            [
                {"type": "text", "label": "Property address", "required": True},
                {"type": "heading", "label": "The dispute"},
                {
                    "type": "select",
                    "label": "Nature of dispute",
                    "options": [{"label": "Boundary"}, {"label": "Easement"}],
                },
                {"type": "date", "label": "When did it start?"},
            ]
        ),
    )


@pytest.fixture
def form_submission(intake, form_template):
    """A form sent to the intake's client, not yet answered."""
    return FormSubmission.objects.create(
        intake=intake,
        template=form_template,
        template_name=form_template.name,
        template_version=form_template.version,
        schema_snapshot=copy.deepcopy(form_template.schema),
        recipient_email="contact@example.com",
    )


@pytest.fixture
def answer_keys(form_template):
    """Field key by label, so tests can address questions by what they say."""
    return {field["label"]: field["key"] for field in form_template.schema}


@pytest.fixture
def filled_submission(form_submission, answer_keys):
    option = form_submission.schema_snapshot[2]["options"][0]["value"]
    form_submission.answers = {
        answer_keys["Property address"]: "225 Paper Street",
        answer_keys["Nature of dispute"]: option,
        answer_keys["When did it start?"]: "2024-03-01",
    }
    form_submission.save()
    return form_submission
