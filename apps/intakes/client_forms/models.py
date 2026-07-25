"""Custom client intake forms: a staff-built template, a per-recipient
submission, and its send log.

A template's questions live in `FormTemplate.schema` — an ordered JSON list of
field objects (see `client_forms/schema.py` for the shape). Sending a form
copies that list into `FormSubmission.schema_snapshot`, so the submission
renders forever as it was asked, no matter how the template is later edited or
whether it is deleted at all. `answers` is keyed by each field's immutable
`key`, which is minted once and survives relabelling.

FKs are declared as strings so this module can be imported from
`apps/intakes/models.py` without a circular import.
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords

from utils.models import AuditMixin


class FormTemplate(AuditMixin, models.Model):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default="")
    # Shown above the questions on the public page. Plain text, never HTML.
    intro_text = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    # Bumped on every schema save. Purely informational — submissions carry
    # their own snapshot, so nothing renders from this. It drives the "sent
    # from v2, template is now v4" notice and makes simple_history legible.
    version = models.PositiveIntegerField(default=1)
    # Ordered list of field objects:
    #   [{"key": "property_address_a1b2c3", "type": "text",
    #     "label": "Property address", "help": "", "required": true,
    #     ...type-specific keys...}, ...]
    # See client_forms/schema.py FIELD_TYPES for the per-type keys.
    schema = models.JSONField(default=list, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name} (v{self.version})"

    @property
    def question_count(self):
        from apps.intakes.client_forms.schema import LAYOUT_TYPES

        return sum(
            1
            for field in self.schema or []
            if isinstance(field, dict) and field.get("type") not in LAYOUT_TYPES
        )

    @property
    def is_sendable(self):
        return self.is_active and self.question_count > 0

    class Meta:
        db_table = "app_intake_form_template"
        ordering = ["name"]


class FormSubmission(AuditMixin, models.Model):
    STATUS_CHOICES = (
        ("SENT", "Sent"),
        ("OPENED", "Opened"),
        ("SUBMITTED", "Submitted"),
        ("CLOSED", "Closed"),
        ("CANCELED", "Canceled"),
    )
    # Statuses the client may still type into.
    FILLABLE = ("SENT", "OPENED", "SUBMITTED")

    # Signed into the public link; never the pk. Rotating it revokes every
    # outstanding link for this submission (see utils/signing.py).
    uuid = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    intake = models.ForeignKey(
        "intakes.Intake", on_delete=models.CASCADE, related_name="form_submissions"
    )
    # SET_NULL, not CASCADE: deleting a template must never destroy answers a
    # client already gave. The snapshot and template_name carry it alone.
    template = models.ForeignKey(
        "intakes.FormTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    template_name = models.CharField(max_length=120)
    template_version = models.PositiveIntegerField(default=1)
    # Frozen copy of FormTemplate.schema at send time. The only thing the
    # public page and the staff read view ever render from.
    schema_snapshot = models.JSONField(default=list)
    # {"<field key>": <value>}; value type per field type — see schema.py.
    answers = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="SENT")
    recipient_email = models.CharField(max_length=255, blank=True, default="")
    opened_at = models.DateTimeField(null=True, blank=True)
    last_saved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Timeline breadcrumb filed on the intake when the client submits. Fixed
    # text only — Note.details is rendered through markdown then |safe, so
    # routing client-supplied answers into it would be a stored-XSS hole.
    note = models.ForeignKey(
        "intakes.Note",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # answers churn on every autosave; a history row per keystroke batch is
    # noise. Status transitions still write one.
    history = HistoricalRecords(excluded_fields=["answers", "last_saved_at"])

    def __str__(self):
        return f"{self.template_name} → intake {self.intake_id} ({self.status})"

    @property
    def is_fillable(self):
        return self.status in self.FILLABLE

    @property
    def template_drifted(self):
        """The live template has moved on from the version this was sent with."""
        return bool(self.template and self.template.version != self.template_version)

    @property
    def answered_count(self):
        from apps.intakes.client_forms.schema import is_answered

        return sum(1 for value in (self.answers or {}).values() if is_answered(value))

    @property
    def question_count(self):
        from apps.intakes.client_forms.schema import LAYOUT_TYPES

        return sum(
            1
            for field in self.schema_snapshot or []
            if isinstance(field, dict) and field.get("type") not in LAYOUT_TYPES
        )

    class Meta:
        db_table = "app_intake_form_submission"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intake"]),
            models.Index(fields=["status"]),
        ]


class FormSubmissionTransmission(AuditMixin, models.Model):
    """One row per delivery attempt — an email, a reminder, or staff copying
    the link. Mirrors PaymentRequestTransmission and powers the ×N send badge.
    """

    KIND_CHOICES = (
        ("send", "Send"),
        ("reminder", "Reminder"),
        ("link", "Link copied"),
    )
    STATUS_CHOICES = (("sent", "Sent"), ("failed", "Failed"))

    submission = models.ForeignKey(
        FormSubmission, on_delete=models.CASCADE, related_name="transmissions"
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="send")
    sent_at = models.DateTimeField()
    # May hold several comma-separated addresses, so CharField rather than
    # EmailField (which validates a single address).
    to_email = models.CharField(max_length=500, blank=True, default="")
    cc_email = models.CharField(max_length=500, blank=True, default="")
    sent_by = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error = models.TextField(blank=True, default="")

    def __str__(self):
        return (
            f"Submission #{self.submission_id} {self.kind} "
            f"{self.status} to {self.to_email}"
        )

    class Meta:
        db_table = "app_intake_form_transmission"
        ordering = ["-sent_at"]
        indexes = [models.Index(fields=["submission"])]


def seed_templates():
    """The bundled starter forms, transcribed from the Craig Legal website's
    live questionnaires (see the seed_intake_forms management command).

    Field keys in this file are frozen deliberately: re-seeding an environment
    that already holds submissions must land on the same keys, or answers
    already given would stop lining up with their questions.
    """
    import json
    import pathlib

    path = pathlib.Path(__file__).parent / "seed_data" / "craig_legal_forms.json"
    return json.loads(path.read_text())


def submissions_for_intake(intake):
    """Every form sent to an intake, newest first, with its send tally — the
    query behind the intake detail page's forms card."""
    return (
        FormSubmission.objects.filter(intake=intake)
        .select_related("template")
        .annotate(send_count=models.Count("transmissions"))
    )
