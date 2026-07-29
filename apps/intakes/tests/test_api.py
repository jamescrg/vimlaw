import json

import pytest
from django.test import Client, override_settings

from apps.intakes.models import Intake, Note

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _unenforced_seam(settings):
    """Pin the no-key default regardless of the developer's .env; the
    auth-mode tests opt back in with @override_settings."""
    settings.KOSMOS_SEAM_KEY = ""


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


# ---------------------------------------------------------------------------
# The seam key: when KOSMOS_SEAM_KEY is configured, every seam endpoint
# requires the matching X-Seam-Key header. The tests above run with the
# default empty key and double as the unenforced-mode pins.
# ---------------------------------------------------------------------------


def post_intake_with_key(payload, key):
    return Client().post(
        "/api/receive-intake/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-Seam-Key": key} if key else None,
    )


@override_settings(KOSMOS_SEAM_KEY="s3cret")
def test_receive_intake_rejects_missing_or_wrong_seam_key():
    assert post_intake({"full_name": "J", "report": "R"}).status_code == 403
    assert (
        post_intake_with_key({"full_name": "J", "report": "R"}, "wrong").status_code
        == 403
    )
    assert Intake.objects.count() == 0


@override_settings(KOSMOS_SEAM_KEY="s3cret")
def test_receive_intake_accepts_correct_seam_key():
    response = post_intake_with_key({"full_name": "J", "report": "R"}, "s3cret")
    assert response.status_code == 200
    assert response.json()["success"]


@override_settings(KOSMOS_SEAM_KEY="s3cret")
def test_receive_inquiry_requires_seam_key():
    payload = {
        "full_name": "Jane Roe",
        "phone_number": "4045550100",
        "email": "jane@example.com",
        "summary": "Fence dispute.",
    }
    assert post_inquiry(payload).status_code == 403
    ok = Client().post(
        "/api/receive-inquiry/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-Seam-Key": "s3cret"},
    )
    assert ok.status_code == 200


@override_settings(KOSMOS_SEAM_KEY="s3cret")
def test_search_requires_seam_key():
    assert Client().get("/api/intakes/search/", {"q": "Jane"}).status_code == 403
    ok = Client().get(
        "/api/intakes/search/", {"q": "Jane"}, headers={"X-Seam-Key": "s3cret"}
    )
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# The search endpoint: the website office's window into the roster,
# consulted before minting client-form links so phone-logged intakes
# are attached rather than duplicated.
# ---------------------------------------------------------------------------


def search(q):
    return Client().get("/api/intakes/search/", {"q": q})


def make_intake(**kwargs):
    from datetime import date

    defaults = {"name": "Jane Roe", "date": date(2026, 7, 20), "status": "Open"}
    defaults.update(kwargs)
    return Intake.objects.create(**defaults)


def test_search_numeric_q_matches_id_exactly():
    target = make_intake(name="Jane Roe")
    make_intake(name="Other Person")
    body = search(str(target.id)).json()
    assert body["success"]
    assert [r["id"] for r in body["results"]] == [target.id]


def test_search_numeric_q_matches_phone_fragment():
    # Digits match digits regardless of how the phone was typed
    target = make_intake(name="Jane Roe", phone="404-555-0122")
    body = search("5550122").json()
    assert [r["id"] for r in body["results"]] == [target.id]


def test_search_dashed_q_matches_undashed_phone():
    target = make_intake(name="Jane Roe", phone="4045550122")
    body = search("555-0122").json()
    assert [r["id"] for r in body["results"]] == [target.id]


def test_search_text_q_matches_name_case_insensitively():
    target = make_intake(name="Jane Roe")
    make_intake(name="Someone Else")
    body = search("jane").json()
    assert [r["id"] for r in body["results"]] == [target.id]


def test_search_returns_expected_shape():
    from apps.matters.models import PracticeArea

    area, _ = PracticeArea.objects.get_or_create(name="Boundary")
    make_intake(
        name="Jane Roe",
        phone="4045550100",
        email="jane@example.com",
        status="Unresponsive",
        practice_area=area,
    )
    bare = make_intake(name="Jane Doe", date=None, phone=None, email=None)
    body = search("Jane").json()
    rows = {r["name"]: r for r in body["results"]}
    full = rows["Jane Roe"]
    assert full["phone"] == "4045550100"
    assert full["email"] == "jane@example.com"
    assert full["status"] == "Unresponsive"
    assert full["date"] == "2026-07-20"
    assert full["practice_area"] == "Boundary"
    empty = rows["Jane Doe"]
    assert empty["id"] == bare.id
    assert empty["phone"] == ""
    assert empty["email"] == ""
    assert empty["date"] == ""
    assert empty["practice_area"] == ""


def test_search_caps_at_twenty_most_recent():
    for i in range(25):
        make_intake(name=f"Jane {i}")
    body = search("Jane").json()
    assert len(body["results"]) == 20
    ids = [r["id"] for r in body["results"]]
    assert ids == sorted(ids, reverse=True)


def test_search_blank_q_lists_open_roster():
    open_intake = make_intake(name="Jane Roe", status="Open")
    make_intake(name="Gone Quiet", status="Unresponsive")
    make_intake(name="Signed Up", status="Accepted")
    body = search("   ").json()
    assert [r["id"] for r in body["results"]] == [open_intake.id]


def test_search_rejects_post():
    assert Client().post("/api/intakes/search/").status_code == 405


# --- Repeat inquiries thread onto existing intakes ---------------------------


INQUIRY = {
    "full_name": "Jane Roe",
    "phone_number": "4045550100",
    "email": "jane@example.com",
    "summary": "My neighbor's fence is on my land.",
}


def test_repeat_inquiry_by_email_appends_note():
    first = post_inquiry(INQUIRY)
    intake_id = first.json()["intake_id"]

    second = post_inquiry({**INQUIRY, "summary": "Following up on my fence issue."})
    assert second.json()["intake_id"] == intake_id
    assert Intake.objects.count() == 1
    notes = Note.objects.filter(intake_id=intake_id).order_by("id")
    assert notes.count() == 2
    assert "Following up" in notes.last().details


def test_repeat_inquiry_fills_missing_phone():
    intake = Intake.objects.create(
        name="Jane Roe", email="jane@example.com", status="Open", date="2026-01-01"
    )
    post_inquiry(INQUIRY)
    intake.refresh_from_db()
    assert intake.phone == "4045550100"
    note = Note.objects.get()
    assert "New phone: 4045550100" in note.details
    assert "fence is on my land" in note.details


def test_repeat_inquiry_matches_by_phone():
    intake = Intake.objects.create(
        name="Jane Roe", phone="404.555.0100", status="Open", date="2026-01-01"
    )
    post_inquiry({**INQUIRY, "email": "different@example.com"})
    assert Intake.objects.count() == 1
    intake.refresh_from_db()
    assert intake.email == "different@example.com"


def test_repeat_inquiry_reopens_unresponsive():
    Intake.objects.create(
        name="Jane Roe",
        email="jane@example.com",
        status="Unresponsive",
        date="2026-01-01",
    )
    post_inquiry(INQUIRY)
    assert Intake.objects.get().status == "Open"


def test_repeat_inquiry_leaves_pending_alone():
    Intake.objects.create(
        name="Jane Roe",
        email="jane@example.com",
        status="Pending",
        date="2026-01-01",
    )
    post_inquiry(INQUIRY)
    assert Intake.objects.get().status == "Pending"
