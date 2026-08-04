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

from django.db import models

from utils.models import AuditMixin


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
        "case.Conversation",
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

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.matter.name})"

    @property
    def current_version(self):
        return self.versions.order_by("-seq").first()


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
