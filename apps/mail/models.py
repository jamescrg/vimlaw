from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from utils.models import AuditMixin

# AI context inclusion modes (mirrors apps.case.models.AI_CONTEXT_CHOICES).
AI_CONTEXT_CHOICES = [
    ("auto", "Auto"),
    ("always", "Always"),
    ("never", "Never"),
]


class Email(AuditMixin, models.Model):
    """A Gmail message synced onto a matter via its mapped Gmail label.

    Text-only record: Gmail remains the archive of record and ``gmail_id``
    deep-links back to the original message. Attachments are recorded as
    metadata only (never fetched). Rows are immutable once synced — the sync
    skips existing (matter, gmail_id) pairs so ``updated_at`` stays honest for
    the auto-summary's ``since=`` incremental filtering.
    """

    matter = models.ForeignKey(
        "matters.Matter", on_delete=models.CASCADE, related_name="emails"
    )
    gmail_id = models.CharField(max_length=32)
    thread_id = models.CharField(max_length=32, db_index=True)
    # The mapped label that matched at sync time (snapshot; labels can be
    # remapped later without rewriting rows).
    label_id = models.CharField(max_length=64, blank=True)
    sender = models.CharField(max_length=500, blank=True)
    # To + Cc, comma-joined raw address lists.
    recipients = models.TextField(blank=True)
    # RFC 5322 caps a header line at 998 characters.
    subject = models.CharField(max_length=998, blank=True)
    # From Gmail's internalDate — more reliable than the Date header.
    date = models.DateTimeField(null=True, db_index=True)
    snippet = models.CharField(max_length=500, blank=True)
    body_text = models.TextField(blank=True)
    BODY_SOURCE_CHOICES = [("plain", "Plain text"), ("html", "HTML")]
    body_source = models.CharField(
        max_length=10, choices=BODY_SOURCE_CHOICES, default="plain"
    )
    # [{"filename": str, "mime_type": str, "size": int}] — metadata only.
    attachments = models.JSONField(default=list, blank=True)
    # Email is voluminous and mostly supporting material, so it defaults a
    # notch below Documents/Notes (4).
    importance = models.PositiveIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    ai_context = models.CharField(
        max_length=6, choices=AI_CONTEXT_CHOICES, default="auto"
    )
    synced_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.subject or '(no subject)'} — {self.sender}"

    @property
    def gmail_url(self):
        return f"https://mail.google.com/mail/u/0/#all/{self.gmail_id}"

    @property
    def sender_display(self):
        """Display name from the From header (address when unnamed)."""
        from email.utils import parseaddr

        name, addr = parseaddr(self.sender or "")
        return name or addr

    @property
    def recipients_display(self):
        """Display names from the To+Cc headers, comma-joined."""
        from email.utils import getaddresses

        pairs = getaddresses([self.recipients or ""])
        return ", ".join(name or addr for name, addr in pairs)

    class Meta:
        db_table = "app_email"
        ordering = ["-date"]
        constraints = [
            # A message under two mapped labels becomes one row per matter —
            # it is context for both cases.
            models.UniqueConstraint(
                fields=["matter", "gmail_id"], name="unique_email_per_matter"
            )
        ]
        indexes = [models.Index(fields=["matter", "thread_id"])]


class GmailSyncState(models.Model):
    """Stores the Gmail history API cursor for incremental sync.

    A single row, mirroring apps.drive.models.DriveSyncState: ``history_id``
    is the ``startHistoryId`` for the next ``users.history.list`` call; a
    stale cursor (HTTP 404) clears it and triggers a full re-bootstrap.
    """

    history_id = models.CharField(max_length=32, null=True, blank=True)
    # Mapped label ids no longer present in Gmail (label deleted) — surfaced
    # as a drift warning on the integrations page.
    missing_labels = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sync_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Gmail sync state (cursor set: {bool(self.history_id)})"

    class Meta:
        db_table = "app_gmail_sync_state"
