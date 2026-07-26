"""End-to-end: build a form, send it, fill it in as the client, read it back.

Walks the same path a real user does, across the staff app and the public page,
so the seams between the phases are exercised together rather than only in
isolation.
"""

import json

import pytest
from django.test import Client as DjangoClient
from django.urls import reverse

from apps.intakes.client_forms.links import form_path
from apps.intakes.models import FormSubmission, FormTemplate
from apps.settings.models import Firm

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def firm():
    return Firm.objects.create(name="Craig Legal, PLLC", email="office@example.com")


def post_json(client, url, payload):
    return client.post(url, json.dumps(payload), content_type="application/json")


def test_build_send_fill_and_read_back(client, intake):
    anon = DjangoClient()

    # --- Staff builds a form -------------------------------------------------
    client.post(
        reverse("intakes:form-template-new"),
        {
            "name": "Boundary Dispute",
            "description": "",
            "intro_text": "Welcome.",
            "is_active": "on",
        },
    )
    template = FormTemplate.objects.get(name="Boundary Dispute")

    save = client.post(
        reverse("intakes:form-builder-save", kwargs={"template_id": template.id}),
        json.dumps(
            {
                "name": "Boundary Dispute",
                "schema": [
                    {"type": "heading", "label": "About the property"},
                    {"type": "text", "label": "Property address", "required": True},
                    {
                        "type": "select",
                        "label": "Do you own it?",
                        "options": [{"label": "I own it"}, {"label": "I rent it"}],
                    },
                    {"type": "yesno", "label": "Is there a written agreement?"},
                ],
            }
        ),
        content_type="application/json",
    )
    schema = save.json()["schema"]
    keys = {field["label"]: field["key"] for field in schema}

    # --- Staff adds it, then sends it as a separate step ---------------------
    client.post(
        reverse("intakes:form-add", kwargs={"id": intake.id}),
        {"template": template.id},
    )
    submission = FormSubmission.objects.get(intake=intake)
    assert submission.status == "DRAFT"

    client.post(
        reverse("intakes:form-submission-send", kwargs={"sub_id": submission.id}),
        {"to": "gandhi@example.com", "action": "email"},
    )
    submission.refresh_from_db()
    assert submission.status == "SENT"
    url = form_path(submission)

    # --- Client opens it, with no account ------------------------------------
    page = anon.get(url)
    assert page.status_code == 200
    body = page.content.decode()
    assert "About the property" in body
    assert "Property address" in body
    assert "I own it" in body

    submission.refresh_from_db()
    assert submission.status == "OPENED"

    # --- Client answers the optional questions first -------------------------
    own = schema[2]["options"][0]["value"]
    post_json(
        anon, url.rstrip("/") + "/save/", {"answers": {keys["Do you own it?"]: own}}
    )
    post_json(
        anon,
        url.rstrip("/") + "/save/",
        {"answers": {keys["Is there a written agreement?"]: False}},
    )

    # Submitting is refused while the required question is still blank.
    blocked = post_json(anon, url.rstrip("/") + "/submit/", {"answers": {}})
    assert blocked.status_code == 400
    assert keys["Property address"] in blocked.json()["errors"]

    # A second sitting sends only the missing answer; the earlier two, saved
    # separately, must still be there and still count.
    done = post_json(
        anon,
        url.rstrip("/") + "/submit/",
        {"answers": {keys["Property address"]: "225 Paper Street"}},
    )
    assert done.status_code == 200

    submission.refresh_from_db()
    assert submission.status == "SUBMITTED"
    assert submission.note is not None

    # --- Staff edits the form afterwards; the submission must not move -------
    client.post(
        reverse("intakes:form-builder-save", kwargs={"template_id": template.id}),
        json.dumps({"schema": [{"type": "text", "label": "Completely different"}]}),
        content_type="application/json",
    )

    review = client.get(
        reverse("intakes:form-submission", kwargs={"sub_id": submission.id})
    )
    read_back = review.content.decode()
    assert "Property address" in read_back
    assert "225 Paper Street" in read_back
    assert "I own it" in read_back  # the option label, not its stored value
    assert "No" in read_back  # the yes/no answer
    assert "Completely different" not in read_back
    assert "has since changed" in read_back


def test_the_settings_modal_cannot_overwrite_a_name_edited_in_the_builder(
    client, form_template
):
    """The builder toolbar owns the name; the settings modal must not offer it."""
    response = client.get(
        reverse(
            "intakes:form-template-settings", kwargs={"template_id": form_template.id}
        )
    )
    assert response.status_code == 200
    assert 'name="name"' not in response.content.decode()

    client.post(
        reverse(
            "intakes:form-template-settings", kwargs={"template_id": form_template.id}
        ),
        {
            "description": "Updated",
            "intro_text": "",
            "is_active": "on",
            "name": "Hijacked",
        },
    )
    form_template.refresh_from_db()
    assert form_template.name == "Property Dispute Questionnaire"
    assert form_template.description == "Updated"
