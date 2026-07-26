import json

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.intakes.client_forms.models import FormSubmission
from apps.settings.models import Firm

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def firm():
    return Firm.objects.create(name="Craig Legal, PLLC", email="office@example.com")


def add_url(intake):
    return reverse("intakes:form-add", kwargs={"id": intake.id})


def send_url(submission):
    return reverse("intakes:form-submission-send", kwargs={"sub_id": submission.id})


def add_then(client, intake, template):
    """Walk step one so a test can get at step two."""
    client.post(add_url(intake), {"template": template.id})
    return FormSubmission.objects.get(intake=intake)


class TestAddingAForm:
    """Step one: create the form. Nothing leaves the building."""

    def test_adding_snapshots_the_template_and_sends_nothing(
        self, client, intake, form_template
    ):
        response = client.post(add_url(intake), {"template": form_template.id})
        assert response.status_code == 204

        submission = FormSubmission.objects.get(intake=intake)
        assert submission.schema_snapshot == form_template.schema
        assert submission.template_name == form_template.name
        assert submission.template_version == form_template.version
        assert submission.status == "DRAFT"
        assert submission.sent_at is None
        assert not mail.outbox
        assert not submission.transmissions.exists()

    def test_the_snapshot_is_a_copy_not_a_reference(
        self, client, intake, form_template
    ):
        """Editing the template afterwards must not reach into what was sent."""
        submission = add_then(client, intake, form_template)

        form_template.schema[0]["label"] = "Mutated in place"
        form_template.save()

        submission.refresh_from_db()
        assert submission.schema_snapshot[0]["label"] == "Property address"

    def test_a_draft_link_already_works(self, client, intake, form_template):
        """Staff can copy it into their own email, so it can't be inert."""
        from django.test import Client as DjangoClient

        from apps.intakes.client_forms.links import form_path

        submission = add_then(client, intake, form_template)
        assert DjangoClient().get(form_path(submission)).status_code == 200

    def test_a_form_with_no_questions_cannot_be_added(self, client, intake):
        from apps.intakes.models import FormTemplate

        empty = FormTemplate.objects.create(name="Empty", schema=[])
        response = client.post(add_url(intake), {"template": empty.id})
        assert response.status_code == 200
        assert "no questions yet" in response.content.decode()
        assert not FormSubmission.objects.filter(intake=intake).exists()

    def test_an_inactive_form_is_not_offered(self, client, intake, form_template):
        form_template.is_active = False
        form_template.save()
        body = client.get(add_url(intake)).content.decode()
        assert form_template.name not in body


class TestSendingAForm:
    """Step two: hand it over."""

    def test_emailing_sends_a_message_and_marks_it_sent(
        self, client, intake, form_template
    ):
        submission = add_then(client, intake, form_template)
        response = client.post(
            send_url(submission), {"to": "client@example.com", "action": "email"}
        )
        assert response.status_code == 204

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["client@example.com"]
        assert "Craig Legal" in message.subject
        assert "/form/" in message.body

        submission.refresh_from_db()
        assert submission.status == "SENT"
        assert submission.sent_at is not None
        assert submission.recipient_email == "client@example.com"
        assert submission.transmissions.get().kind == "send"

    def test_the_email_is_not_from_the_billing_address(
        self, client, intake, form_template
    ):
        submission = add_then(client, intake, form_template)
        client.post(send_url(submission), {"to": "c@example.com", "action": "email"})
        assert "Billing" not in mail.outbox[0].from_email

    def test_copying_the_link_also_counts_as_sending(
        self, client, intake, form_template
    ):
        """The client has the link either way, so the row must say so."""
        submission = add_then(client, intake, form_template)
        response = client.post(
            send_url(submission), {"to": "c@example.com", "action": "link"}
        )
        assert response.status_code == 200
        assert "/form/" in response.content.decode()
        # The list behind the modal refreshes, but the modal stays open.
        assert response["HX-Trigger"] == "intakeFormsChanged"
        assert not mail.outbox

        submission.refresh_from_db()
        assert submission.status == "SENT"
        assert submission.transmissions.get().kind == "link"

    def test_a_bad_address_re_renders_the_modal_and_leaves_it_a_draft(
        self, client, intake, form_template
    ):
        submission = add_then(client, intake, form_template)
        response = client.post(
            send_url(submission), {"to": "not-an-address", "action": "email"}
        )
        assert response.status_code == 200
        assert "Invalid email address" in response.content.decode()
        assert not mail.outbox

        submission.refresh_from_db()
        assert submission.status == "DRAFT"
        assert submission.transmissions.get().status == "failed"

    def test_sending_twice_does_not_rewind_a_submitted_form(
        self, client, intake, form_template
    ):
        submission = add_then(client, intake, form_template)
        submission.status = "SUBMITTED"
        submission.save()

        client.post(send_url(submission), {"to": "c@example.com", "action": "email"})
        submission.refresh_from_db()
        assert submission.status == "SUBMITTED"


class TestStatusActions:
    def status_url(self, submission, action):
        return reverse(
            "intakes:form-submission-status",
            kwargs={"sub_id": submission.id, "status": action},
        )

    def test_locking_then_reopening(self, client, form_submission):
        client.post(self.status_url(form_submission, "lock"))
        form_submission.refresh_from_db()
        assert form_submission.status == "CLOSED"
        assert form_submission.closed_at is not None

        client.post(self.status_url(form_submission, "reopen"))
        form_submission.refresh_from_db()
        assert form_submission.closed_at is None

    def test_reopening_returns_to_how_far_it_actually_got(
        self, client, form_submission
    ):
        """A form the client never opened must not come back as Submitted."""
        form_submission.status = "SENT"
        form_submission.sent_at = timezone.now()
        form_submission.save()

        client.post(self.status_url(form_submission, "lock"))
        client.post(self.status_url(form_submission, "reopen"))
        form_submission.refresh_from_db()
        assert form_submission.status == "SENT"

    def test_cancelling_kills_the_link_without_touching_the_uuid(
        self, client, form_submission
    ):
        """Cancel is the cheap way to stop a link working — form_page 410s a
        canceled form, so the URL dies while the uuid stays put."""
        from django.test import Client as DjangoClient

        from apps.intakes.client_forms.links import form_path

        before = form_submission.uuid
        url = form_path(form_submission)

        client.post(self.status_url(form_submission, "cancel"))
        form_submission.refresh_from_db()

        assert form_submission.status == "CANCELED"
        assert form_submission.uuid == before
        assert DjangoClient().get(url).status_code == 410

    def test_reverting_to_draft_clears_the_sent_stamp(self, client, form_submission):
        form_submission.status = "SENT"
        form_submission.sent_at = timezone.now()
        form_submission.save()

        client.post(self.status_url(form_submission, "draft"))
        form_submission.refresh_from_db()
        assert form_submission.status == "DRAFT"
        assert form_submission.sent_at is None

    def test_a_canceled_form_can_be_brought_back(self, client, form_submission):
        client.post(self.status_url(form_submission, "cancel"))
        client.post(self.status_url(form_submission, "draft"))
        form_submission.refresh_from_db()
        assert form_submission.status == "DRAFT"

    def test_an_unknown_action_is_rejected(self, client, form_submission):
        assert (
            client.post(self.status_url(form_submission, "explode")).status_code == 400
        )

    def test_offered_actions_depend_on_the_state(self, form_submission):
        # Complete is reachable straight from Draft: staff fill plenty of
        # these in themselves and the client never sees them.
        form_submission.status = "DRAFT"
        assert [a for a, _ in form_submission.status_actions] == ["complete", "cancel"]

        form_submission.status = "SUBMITTED"
        assert "complete" not in [a for a, _ in form_submission.status_actions]

        form_submission.status = "CANCELED"
        assert [a for a, _ in form_submission.status_actions] == ["draft"]

        form_submission.status = "CLOSED"
        assert "reopen" in [a for a, _ in form_submission.status_actions]
        assert "lock" not in [a for a, _ in form_submission.status_actions]

    def test_reissuing_kills_every_link_already_handed_out(
        self, client, form_submission
    ):
        """The token signs the uuid, so rotating it invalidates them all —
        which is what cancel alone can't do, since un-cancelling would hand the
        same URL back."""
        from django.test import Client as DjangoClient

        from apps.intakes.client_forms.links import form_path

        stale = form_path(form_submission)
        response = client.post(
            reverse(
                "intakes:form-submission-reissue",
                kwargs={"sub_id": form_submission.id},
            )
        )
        assert response.status_code == 204

        form_submission.refresh_from_db()
        assert DjangoClient().get(stale).status_code == 404
        assert DjangoClient().get(form_path(form_submission)).status_code == 200


class TestDeleting:
    def delete_url(self, submission):
        return reverse(
            "intakes:form-submission-delete", kwargs={"sub_id": submission.id}
        )

    def test_a_form_added_by_mistake_can_be_deleted(self, client, form_submission):
        response = client.post(self.delete_url(form_submission))
        assert response.status_code == 204
        assert not FormSubmission.objects.filter(pk=form_submission.pk).exists()

    def test_deleting_takes_its_transmissions_with_it(
        self, client, intake, form_template
    ):
        submission = add_then(client, intake, form_template)
        client.post(send_url(submission), {"to": "c@example.com", "action": "link"})
        assert submission.transmissions.exists()

        client.post(self.delete_url(submission))
        assert not FormSubmission.objects.filter(pk=submission.pk).exists()

    def test_the_warning_names_the_answers_that_would_be_lost(
        self, client, intake, filled_submission
    ):
        """A form with answers is the dangerous case, so the confirm text has
        to say what's being destroyed rather than ask a generic question."""
        body = client.get(
            reverse("intakes:forms-panel", kwargs={"id": intake.id})
        ).content.decode()
        assert "answered 3 of 3 questions" in body
        assert "will be deleted with it" in body

    def test_an_unanswered_form_gets_the_plain_warning(
        self, client, intake, form_submission
    ):
        body = client.get(
            reverse("intakes:forms-panel", kwargs={"id": intake.id})
        ).content.decode()
        assert "cannot be undone" in body
        assert "will be deleted with it" not in body

    def test_delete_requires_post(self, client, form_submission):
        assert client.get(self.delete_url(form_submission)).status_code == 405


class TestStaffFill:
    """The page a paralegal opens to take a form down over the phone. It
    replaced the read-only review modal, so it has to carry what that showed."""

    def test_it_shows_the_questions_as_asked_with_the_answers_so_far(
        self, client, filled_submission
    ):
        response = client.get(
            reverse(
                "intakes:form-submission-fill", kwargs={"sub_id": filled_submission.id}
            )
        )
        body = response.content.decode()
        assert response.status_code == 200
        assert "Property address" in body
        assert "225 Paper Street" in body
        # The staff bar, so nobody mistakes this tab for the client's copy.
        assert "Filling in for" in body

    def test_it_flags_a_template_that_has_moved_on(
        self, client, filled_submission, form_template
    ):
        form_template.version += 1
        form_template.save()
        body = client.get(
            reverse(
                "intakes:form-submission-fill", kwargs={"sub_id": filled_submission.id}
            )
        ).content.decode()
        assert "has since changed" in body

    def test_opening_it_does_not_claim_the_client_opened_the_form(
        self, client, filled_submission
    ):
        """`opened_at` has to keep meaning the client looked at it — staff
        working the form must not forge that signal."""
        filled_submission.status = "SENT"
        filled_submission.opened_at = None
        filled_submission.save()

        client.get(
            reverse(
                "intakes:form-submission-fill", kwargs={"sub_id": filled_submission.id}
            )
        )

        filled_submission.refresh_from_db()
        assert filled_submission.opened_at is None
        assert filled_submission.status == "SENT"

    def test_staff_can_complete_it_straight_from_draft(
        self, client, form_submission, answer_keys
    ):
        """The paralegal path: created, never sent, filled in on the call."""
        assert form_submission.status == "DRAFT"

        response = client.post(
            reverse(
                "intakes:form-submission-fill-complete",
                kwargs={"sub_id": form_submission.id},
            ),
            json.dumps(
                {"answers": {answer_keys["Property address"]: "225 Paper Street"}}
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        form_submission.refresh_from_db()
        assert form_submission.status == "SUBMITTED"
        assert form_submission.submitted_at is not None
        # Never sent, so it must not claim it was.
        assert form_submission.sent_at is None
        assert "225 Paper Street" in form_submission.note.details

    def test_a_staff_completion_is_attributed_to_the_person_who_took_it(
        self, client, django_user_model, form_submission, answer_keys
    ):
        """The client's own submissions have no user; one taken down over the
        phone should say who wrote it."""
        client.post(
            reverse(
                "intakes:form-submission-fill-complete",
                kwargs={"sub_id": form_submission.id},
            ),
            json.dumps(
                {"answers": {answer_keys["Property address"]: "225 Paper Street"}}
            ),
            content_type="application/json",
        )

        form_submission.refresh_from_db()
        assert form_submission.note.user is not None

    def test_a_required_question_does_not_block_staff(
        self, client, form_submission, answer_keys
    ):
        """Property address is required. A caller who won't give one must not
        be able to jam the paralegal — the gap shows in the Done count."""
        response = client.post(
            reverse(
                "intakes:form-submission-fill-complete",
                kwargs={"sub_id": form_submission.id},
            ),
            json.dumps({"answers": {answer_keys["When did it start?"]: "2024-03-01"}}),
            content_type="application/json",
        )

        assert response.status_code == 200
        form_submission.refresh_from_db()
        assert form_submission.status == "SUBMITTED"

    def test_a_malformed_answer_still_fails(self, client, form_submission, answer_keys):
        """Looser on requiredness, not on coercion: a date has to be a date."""
        response = client.post(
            reverse(
                "intakes:form-submission-fill-complete",
                kwargs={"sub_id": form_submission.id},
            ),
            json.dumps({"answers": {answer_keys["When did it start?"]: "whenever"}}),
            content_type="application/json",
        )

        assert response.status_code == 400
        form_submission.refresh_from_db()
        assert form_submission.status == "DRAFT"

    def test_staff_cannot_write_to_a_cancelled_form(
        self, client, form_submission, answer_keys
    ):
        form_submission.status = "CANCELED"
        form_submission.save()

        response = client.post(
            reverse(
                "intakes:form-submission-fill-save",
                kwargs={"sub_id": form_submission.id},
            ),
            json.dumps({"answers": {answer_keys["Property address"]: "nope"}}),
            content_type="application/json",
        )

        assert response.status_code == 409

    def test_the_status_menu_completes_it_too(self, client, filled_submission):
        """Same completion as the fill page, so a form finished on paper and
        one finished on screen leave the record in one shape."""
        response = client.post(
            reverse(
                "intakes:form-submission-status",
                kwargs={"sub_id": filled_submission.id, "status": "complete"},
            )
        )

        assert response.status_code == 204
        filled_submission.refresh_from_db()
        assert filled_submission.status == "SUBMITTED"
        assert filled_submission.note is not None

    def test_it_needs_a_login(self, filled_submission):
        from django.test import Client as DjangoClient

        response = DjangoClient().get(
            reverse(
                "intakes:form-submission-fill", kwargs={"sub_id": filled_submission.id}
            )
        )
        assert response.status_code in (301, 302)
        assert "/login" in response["Location"]

    def test_the_panel_lists_what_was_sent(self, client, intake, filled_submission):
        response = client.get(reverse("intakes:forms-panel", kwargs={"id": intake.id}))
        body = response.content.decode()
        assert response.status_code == 200
        assert filled_submission.template_name in body
        assert "3 / 3" in body  # the card meta line
