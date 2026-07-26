import json
import uuid as uuid_module

import pytest
from django.test import (
    Client as DjangoClient,
    override_settings,
)

from apps.intakes.client_forms.links import form_path
from apps.intakes.client_forms.schema import normalize_schema
from apps.intakes.models import Note

pytestmark = pytest.mark.django_db


@pytest.fixture
def anon():
    """No login at all — this page is for someone with no account."""
    return DjangoClient()


def save_url(submission):
    return form_path(submission).rstrip("/") + "/save/"


def submit_url(submission):
    return form_path(submission).rstrip("/") + "/submit/"


def post_json(client, url, payload):
    return client.post(url, json.dumps(payload), content_type="application/json")


class TestAccess:
    def test_the_fill_page_opens_with_no_login(self, anon, form_submission):
        response = anon.get(form_path(form_submission))
        assert response.status_code == 200
        assert "Property Dispute Questionnaire" in response.content.decode()

    def test_a_user_without_perm_intakes_can_still_open_it(
        self, client, user, form_submission
    ):
        """The public page must not sit under /intakes/, which PermissionMiddleware
        gates on perm_intakes."""
        # Narrow update: saving the whole instance would write back a stale
        # daily-dash check-in and bounce the request to /dash/.
        type(user).objects.filter(pk=user.pk).update(role="USER", perm_intakes=False)

        assert not form_path(form_submission).startswith("/intakes/")
        assert client.get(form_path(form_submission)).status_code == 200

    def test_first_open_marks_it_opened_exactly_once(self, anon, form_submission):
        """Even from DRAFT: if the client is reading it, staff handed the link
        over somehow, and the row shouldn't still claim it was never sent."""
        assert form_submission.status == "DRAFT"
        anon.get(form_path(form_submission))
        form_submission.refresh_from_db()
        assert form_submission.status == "OPENED"
        first_opened = form_submission.opened_at

        anon.get(form_path(form_submission))
        form_submission.refresh_from_db()
        assert form_submission.opened_at == first_opened

    def test_a_tampered_token_is_not_found(self, anon, form_submission):
        response = anon.get("/form/not-a-real-token/")
        assert response.status_code == 404
        assert "invalid" in response.content.decode().lower()

    @override_settings(INTAKE_FORM_LINK_MAX_AGE=-1)
    def test_an_expired_link_says_so(self, anon, form_submission):
        response = anon.get(form_path(form_submission))
        assert response.status_code == 410
        assert "expired" in response.content.decode().lower()

    def test_revoking_the_uuid_kills_the_outstanding_link(self, anon, form_submission):
        stale = form_path(form_submission)
        form_submission.uuid = uuid_module.uuid4()
        form_submission.save(update_fields=["uuid"])
        assert anon.get(stale).status_code == 404

    def test_a_canceled_form_is_gone(self, anon, form_submission):
        form_submission.status = "CANCELED"
        form_submission.save()
        assert anon.get(form_path(form_submission)).status_code == 410

    def test_a_closed_form_is_read_only(self, anon, filled_submission):
        filled_submission.status = "CLOSED"
        filled_submission.save()
        response = anon.get(form_path(filled_submission))
        body = response.content.decode()

        assert response.status_code == 200
        assert "we've received your answers" in body
        assert "225 Paper Street" in body  # they can still see what they said
        assert 'class="cf-input"' not in body  # but not type into it

    def test_saving_into_a_closed_form_is_refused(
        self, anon, form_submission, answer_keys
    ):
        form_submission.status = "CLOSED"
        form_submission.save()
        response = post_json(
            anon,
            save_url(form_submission),
            {"answers": {answer_keys["Property address"]: "too late"}},
        )
        assert response.status_code == 409


class TestAutosave:
    def test_partial_saves_merge_rather_than_replace(
        self, anon, form_submission, answer_keys
    ):
        """The key guarantee behind page-hide saves racing debounced ones."""
        address, date = (
            answer_keys["Property address"],
            answer_keys["When did it start?"],
        )

        assert (
            post_json(
                anon,
                save_url(form_submission),
                {"answers": {address: "225 Paper Street"}},
            ).status_code
            == 200
        )
        assert (
            post_json(
                anon, save_url(form_submission), {"answers": {date: "2024-03-01"}}
            ).status_code
            == 200
        )

        form_submission.refresh_from_db()
        assert form_submission.answers[address] == "225 Paper Street"
        assert form_submission.answers[date] == "2024-03-01"

    def test_a_draft_saves_without_its_required_answers(self, anon, form_submission):
        response = post_json(anon, save_url(form_submission), {"answers": {}})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_unknown_keys_never_reach_the_database(self, anon, form_submission):
        post_json(anon, save_url(form_submission), {"answers": {"smuggled": "x"}})
        form_submission.refresh_from_db()
        assert "smuggled" not in form_submission.answers

    def test_an_oversized_body_is_refused_before_parsing(self, anon, form_submission):
        response = post_json(
            anon, save_url(form_submission), {"answers": {"a": "x" * 300_000}}
        )
        assert response.status_code == 413

    def test_malformed_json_is_refused(self, anon, form_submission):
        response = anon.post(
            save_url(form_submission), "not json", content_type="application/json"
        )
        assert response.status_code == 400

    def test_autosave_does_not_write_a_history_row(
        self, anon, form_submission, answer_keys
    ):
        before = form_submission.history.count()
        post_json(
            anon,
            save_url(form_submission),
            {"answers": {answer_keys["Property address"]: "225 Paper Street"}},
        )
        form_submission.refresh_from_db()
        assert form_submission.history.count() == before


class TestSubmit:
    def test_a_missing_required_answer_blocks_submission(self, anon, form_submission):
        response = post_json(anon, submit_url(form_submission), {"answers": {}})
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False
        assert "required" in list(body["errors"].values())[0].lower()

        form_submission.refresh_from_db()
        assert form_submission.status != "SUBMITTED"

    def test_a_bad_value_reports_its_own_message_not_missing(self, anon, intake):
        from apps.intakes.models import FormSubmission, FormTemplate

        template = FormTemplate.objects.create(
            name="Contact",
            schema=normalize_schema(
                [{"type": "email", "label": "Your email", "required": True}]
            ),
        )
        submission = FormSubmission.objects.create(
            intake=intake,
            template=template,
            template_name=template.name,
            schema_snapshot=template.schema,
        )
        key = template.schema[0]["key"]

        response = post_json(anon, submit_url(submission), {"answers": {key: "nope"}})
        assert response.status_code == 400
        assert "valid email" in response.json()["errors"][key]

    def test_a_valid_submission_records_the_time_and_files_a_note(
        self, anon, form_submission, answer_keys
    ):
        response = post_json(
            anon,
            submit_url(form_submission),
            {"answers": {answer_keys["Property address"]: "225 Paper Street"}},
        )
        assert response.status_code == 200

        form_submission.refresh_from_db()
        assert form_submission.status == "SUBMITTED"
        assert form_submission.submitted_at is not None
        assert form_submission.note is not None
        assert form_submission.note.type == "Client Form"
        assert form_submission.note.user is None

    def test_the_note_carries_no_client_supplied_text(
        self, anon, form_submission, answer_keys
    ):
        """Note.details is markdown-rendered and emitted with |safe on the staff
        detail page, so nothing the client typed may reach it."""
        payload = "<script>alert('xss')</script>"
        post_json(
            anon,
            submit_url(form_submission),
            {"answers": {answer_keys["Property address"]: payload}},
        )
        form_submission.refresh_from_db()
        assert payload not in form_submission.note.details
        assert "alert" not in form_submission.note.details

    def test_revising_after_submitting_does_not_file_a_second_note(
        self, anon, form_submission, answer_keys
    ):
        key = answer_keys["Property address"]
        post_json(anon, submit_url(form_submission), {"answers": {key: "First"}})
        post_json(anon, submit_url(form_submission), {"answers": {key: "Second"}})

        form_submission.refresh_from_db()
        assert form_submission.answers[key] == "Second"
        assert (
            Note.objects.filter(
                intake=form_submission.intake, type="Client Form"
            ).count()
            == 1
        )

    def test_an_earlier_answer_still_counts_toward_required(
        self, anon, form_submission, answer_keys
    ):
        key = answer_keys["Property address"]
        post_json(
            anon, save_url(form_submission), {"answers": {key: "225 Paper Street"}}
        )
        # Submit sends nothing new — the stored answer must still satisfy it.
        response = post_json(anon, submit_url(form_submission), {"answers": {}})
        assert response.status_code == 200


class TestEscaping:
    def test_a_staff_authored_label_is_escaped_on_the_public_page(self, anon, intake):
        from apps.intakes.models import FormSubmission, FormTemplate

        template = FormTemplate.objects.create(
            name="Hostile",
            schema=normalize_schema(
                [{"type": "text", "label": "<img src=x onerror=alert(1)>"}]
            ),
        )
        submission = FormSubmission.objects.create(
            intake=intake,
            template=template,
            template_name=template.name,
            schema_snapshot=template.schema,
        )
        body = anon.get(form_path(submission)).content.decode()

        assert "<img src=x onerror=alert(1)>" not in body
        assert "&lt;img src=x onerror=alert(1)&gt;" in body

    def test_a_client_answer_is_escaped_in_the_read_only_summary(
        self, anon, filled_submission, answer_keys
    ):
        filled_submission.answers[answer_keys["Property address"]] = "<b>bold</b>"
        filled_submission.status = "CLOSED"
        filled_submission.save()

        body = anon.get(form_path(filled_submission)).content.decode()
        assert "<b>bold</b>" not in body
        assert "&lt;b&gt;bold&lt;/b&gt;" in body
