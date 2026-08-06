"""AI drafting sessions on ODT files from the matter's Drive folder.

A DraftSession pins one Drive ODT ("the draft") to one AI conversation. Each
round of AI-proposed edits is applied server-side as LibreOffice tracked
changes (apps/drive/redline.py), producing an immutable DraftVersion: the
working ODT (redlines accumulated against the original), a PDF preview
rendered with the redlines shown, the Markdown facsimile the AI reads, and
the edit list that produced it. Publish is the human gate: it marks the
session done and purges all working blobs except the final version's (kept
for download until Drive write-back exists).

Blob hygiene: django_cleanup deletes storage files when a FileField is
cleared or its row is deleted, so purging a version means clearing its file
fields (services._purge_blobs) — the row, facsimile, and edit list survive
as the audit trail.
"""

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

# Imported for the class (not a string label): Conversation lives in
# apps/case/ai/models.py, which is NOT loaded by apps.case's models.py, so a
# lazy 'case.Conversation' reference only resolves if something else has
# imported that module first. The web app always has; a bare shell or a
# management command may not.
from apps.case.ai.models import Conversation
from utils.models import AuditMixin

# A companion counts as connected while its last poll is this recent. The
# extension polls every ~2.5 seconds, so this tolerates a few missed cycles
# without leaving a closed LibreOffice "connected" for long.
COMPANION_WINDOW_SECONDS = 15


def draft_file_path(instance, filename):
    """drafts/{matter_id}/{session_id}/v{seq}.{ext} — pk-independent."""
    ext = filename.split(".")[-1].lower()
    return (
        f"drafts/{instance.session.matter_id}/{instance.session_id}/"
        f"v{instance.seq}.{ext}"
    )


class DraftSession(AuditMixin, models.Model):
    STATUS_CHOICES = [
        ("drafting", "Drafting"),
        ("published", "Published"),
        ("abandoned", "Abandoned"),
    ]

    matter = models.ForeignKey(
        "matters.Matter", on_delete=models.CASCADE, related_name="draft_sessions"
    )
    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="draft_session",
    )
    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="draft_sessions",
    )
    # Snapshot of the Drive file when the session opened. drive_modified is
    # the publish-time conflict check: if the live file's modifiedTime has
    # moved past it, someone edited the draft mid-session.
    drive_file_id = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    drive_path = models.CharField(max_length=500, blank=True)
    drive_modified = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="drafting")
    published_at = models.DateTimeField(null=True, blank=True)
    # LibreOffice companion state. While a companion is connected (its poll
    # loop keeps companion_seen fresh) edit rounds are queued for the live
    # document instead of the headless applier, and companion_text (the
    # Markdown facsimile of the document as the user last had it) becomes
    # the AI's draft context.
    companion_seen = models.DateTimeField(null=True, blank=True)
    companion_text = models.TextField(blank=True)
    companion_text_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.matter.name})"

    @property
    def current_version(self):
        return self.versions.order_by("-seq").first()

    @property
    def companion_active(self):
        return bool(
            self.companion_seen
            and timezone.now() - self.companion_seen
            < timedelta(seconds=COMPANION_WINDOW_SECONDS)
        )


class DraftVersion(models.Model):
    session = models.ForeignKey(
        DraftSession, on_delete=models.CASCADE, related_name="versions"
    )
    seq = models.PositiveIntegerField()
    odt_file = models.FileField(
        upload_to=draft_file_path, max_length=500, null=True, blank=True
    )
    pdf_file = models.FileField(
        upload_to=draft_file_path, max_length=500, null=True, blank=True
    )
    # What the AI reads as context; also the version's lasting text record
    # after its blobs are purged.
    facsimile = models.TextField(blank=True)
    # The redline edits that produced this version ([] for version 0), as
    # [{"old", "new", "replace_all"}] dicts.
    edits = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "seq"], name="unique_draft_version_seq"
            )
        ]

    def __str__(self):
        return f"{self.session.name} v{self.seq}"

    @property
    def is_accepted(self):
        """True for the clean copy accept-and-publish appends."""
        return self.edits == [{"op": "accept_all"}]

    @property
    def is_drive_sync(self):
        """True for a version pulled in from the current Drive copy."""
        return self.edits == [{"op": "refresh_from_drive"}]


def _new_token_key():
    return secrets.token_urlsafe(32)


class CompanionToken(models.Model):
    """A user's API key for the LibreOffice companion extension.

    Created on first visit to the companion setup modal and baked into the
    .oxt that user downloads, so the extension authenticates without any
    manual configuration.
    """

    user = models.OneToOneField(
        "accounts.CustomUser", on_delete=models.CASCADE, related_name="companion_token"
    )
    key = models.CharField(max_length=64, unique=True, default=_new_token_key)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Companion token for {self.user}"

    @classmethod
    def for_user(cls, user):
        token, _ = cls.objects.get_or_create(user=user)
        return token


class CompanionRound(models.Model):
    """One AI edit round queued for a connected companion.

    The chat worker creates the round and blocks on its status; the
    extension picks it up (delivered_at set, never redelivered), applies the
    edits to the live document, and posts the outcome back.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("applied", "Applied"),
        ("failed", "Failed"),
        ("expired", "Expired"),
    ]

    session = models.ForeignKey(
        DraftSession, on_delete=models.CASCADE, related_name="companion_rounds"
    )
    # Wire-form edit dicts, same shape as DraftVersion.edits.
    edits = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    delivered_at = models.DateTimeField(null=True, blank=True)
    # Outcome from the extension: [{"op", "replacements"}] on success.
    result = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    edit_index = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Round {self.id} for session {self.session_id} ({self.status})"
