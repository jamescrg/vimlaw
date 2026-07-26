import pytest
from django.core import mail
from django.urls import reverse

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

    def test_closing_then_reopening(self, client, form_submission):
        client.post(self.status_url(form_submission, "close"))
        form_submission.refresh_from_db()
        assert form_submission.status == "CLOSED"
        assert form_submission.closed_at is not None

        client.post(self.status_url(form_submission, "reopen"))
        form_submission.refresh_from_db()
        assert form_submission.status == "SUBMITTED"
        assert form_submission.closed_at is None

    def test_an_unknown_action_is_rejected(self, client, form_submission):
        assert (
            client.post(self.status_url(form_submission, "explode")).status_code == 400
        )

    def test_revoking_rotates_the_uuid(self, client, form_submission):
        before = form_submission.uuid
        response = client.post(
            reverse(
                "intakes:form-submission-revoke", kwargs={"sub_id": form_submission.id}
            )
        )
        assert response.status_code == 204
        form_submission.refresh_from_db()
        assert form_submission.uuid != before


class TestReview:
    def test_the_review_shows_the_questions_as_asked(self, client, filled_submission):
        response = client.get(
            reverse("intakes:form-submission", kwargs={"sub_id": filled_submission.id})
        )
        body = response.content.decode()
        assert response.status_code == 200
        assert "Property address" in body
        assert "225 Paper Street" in body
        assert "Boundary" in body  # the option label, not its stored value

    def test_the_review_flags_a_template_that_has_moved_on(
        self, client, filled_submission, form_template
    ):
        form_template.version += 1
        form_template.save()
        body = client.get(
            reverse("intakes:form-submission", kwargs={"sub_id": filled_submission.id})
        ).content.decode()
        assert "has since changed" in body

    def test_the_panel_lists_what_was_sent(self, client, intake, filled_submission):
        response = client.get(reverse("intakes:forms-panel", kwargs={"id": intake.id}))
        body = response.content.decode()
        assert response.status_code == 200
        assert filled_submission.template_name in body
        assert "3 of 3 answered" in body
