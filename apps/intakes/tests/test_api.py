import json

import pytest
from django.test import Client

from apps.intakes.models import Intake, Note

pytestmark = pytest.mark.django_db


def post_intake(payload):
    # The endpoint is public ingress: no login, csrf exempt
    return Client().post(
        "/api/receive-intake/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_receive_intake_creates_intake_and_note():
    response = post_intake(
        {
            "full_name": "Jane Roe",
            "phone_number": "4045550100",
            "email": "jane@example.com",
            "address": "12 Oak St, Atlanta, GA",
            "disputed_property": "14 Oak St, Atlanta, GA",
            "report": "CLIENT INTAKE REPORT\nFull name: Jane Roe",
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"]

    intake = Intake.objects.get(id=body["intake_id"])
    assert intake.name == "Jane Roe"
    assert intake.phone == "4045550100"
    assert intake.email == "jane@example.com"
    assert intake.address == "12 Oak St, Atlanta, GA"
    assert intake.disputed_property == "14 Oak St, Atlanta, GA"
    assert intake.status == "Open"
    assert intake.source == "Internet"

    note = Note.objects.get(id=body["note_id"])
    assert note.intake_id == intake.id
    assert note.user is None
    assert note.type == "Client Form"
    assert "CLIENT INTAKE REPORT" in note.details


def test_receive_intake_appends_note_to_existing_intake():
    first = post_intake(
        {"full_name": "Jane Roe", "report": "CLIENT INTAKE REPORT"}
    ).json()
    second = post_intake(
        {
            "full_name": "Jane Roe",
            "report": "BOUNDARY DISPUTE SUPPLEMENT",
            "intake_id": first["intake_id"],
        }
    ).json()
    assert second["success"]
    assert second["intake_id"] == first["intake_id"]
    assert Intake.objects.count() == 1
    assert Note.objects.filter(intake_id=first["intake_id"]).count() == 2


def test_receive_intake_with_stale_id_creates_fresh_intake():
    response = post_intake(
        {"full_name": "Jane Roe", "report": "SUPPLEMENT", "intake_id": 999999}
    )
    assert response.json()["success"]
    assert Intake.objects.count() == 1


def test_receive_intake_truncates_long_addresses():
    response = post_intake(
        {"full_name": "Jane Roe", "report": "R" * 20, "address": "A" * 300}
    )
    intake = Intake.objects.get(id=response.json()["intake_id"])
    assert len(intake.address) == 255


def test_receive_intake_maps_practice_area():
    from apps.matters.models import PracticeArea

    PracticeArea.objects.get_or_create(name="Boundary")
    response = post_intake(
        {
            "full_name": "Jane Roe",
            "report": "CLIENT INTAKE REPORT",
            "dispute_nature": "boundary",
        }
    )
    intake = Intake.objects.get(id=response.json()["intake_id"])
    assert intake.practice_area.name == "Boundary"


def test_receive_intake_unknown_dispute_leaves_area_unset():
    response = post_intake(
        {
            "full_name": "Jane Roe",
            "report": "CLIENT INTAKE REPORT",
            "dispute_nature": "something-new",
        }
    )
    intake = Intake.objects.get(id=response.json()["intake_id"])
    assert intake.practice_area is None


def test_receive_intake_missing_fields_400():
    assert post_intake({"full_name": "Jane Roe"}).status_code == 400
    assert post_intake({"report": "no name and no intake id"}).status_code == 400


def test_receive_intake_bad_json_400():
    response = Client().post(
        "/api/receive-intake/", data="not json", content_type="application/json"
    )
    assert response.status_code == 400


def post_inquiry(payload):
    return Client().post(
        "/api/receive-inquiry/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_receive_inquiry_returns_intake_id_and_files_note():
    # The website depends on this contract: the returned intake_id is
    # the binding that later client-form reports attach to
    response = post_inquiry(
        {
            "full_name": "Jane Roe",
            "phone_number": "4045550100",
            "email": "jane@example.com",
            "summary": "My neighbor moved a fence onto my land.",
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"]

    intake = Intake.objects.get(id=body["intake_id"])
    assert intake.name == "Jane Roe"
    assert intake.phone == "4045550100"
    assert intake.email == "jane@example.com"
    assert intake.status == "Open"

    note = Note.objects.get(intake=intake)
    assert note.user is None
    assert note.type == "Email In"
    assert "fence onto my land" in note.details


def test_receive_inquiry_missing_fields_400():
    response = post_inquiry({"full_name": "Jane Roe"})
    assert response.status_code == 400
    assert not response.json()["success"]


def test_receive_inquiry_bad_json_400():
    response = Client().post(
        "/api/receive-inquiry/",
        data="{not json",
        content_type="application/json",
    )
    assert response.status_code == 400


def test_receive_intake_updates_note_in_place():
    first = post_intake(
        {"full_name": "Jane Roe", "report": "# Client Intake Report v1"}
    ).json()
    second = post_intake(
        {
            "intake_id": first["intake_id"],
            "note_id": first["note_id"],
            "report": "# Client Intake Report v2\n\n*Last updated today.*",
        }
    ).json()
    assert second["success"]
    assert second["note_id"] == first["note_id"]
    assert Note.objects.filter(intake_id=first["intake_id"]).count() == 1
    note = Note.objects.get(id=first["note_id"])
    assert "v2" in note.details
    assert "v1" not in note.details


def test_receive_intake_stale_note_id_files_fresh_note():
    first = post_intake(
        {"full_name": "Jane Roe", "report": "# Client Intake Report"}
    ).json()
    response = post_intake(
        {
            "intake_id": first["intake_id"],
            "note_id": 999999,
            "report": "# Another Report",
        }
    ).json()
    assert response["success"]
    assert response["note_id"] != 999999
    assert Note.objects.filter(intake_id=first["intake_id"]).count() == 2
