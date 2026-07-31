import json

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from utils.models import AuditMixin

# Label create/update scope: message content stays read-only.
GMAIL_LABELS_SCOPE = "https://www.googleapis.com/auth/gmail.labels"

# AI context inclusion modes (mirrors apps.case.models.AI_CONTEXT_CHOICES).
AI_CONTEXT_CHOICES = [
    ("auto", "Auto"),
    ("always", "Always"),
    ("never", "Never"),
]


class GmailAccount(models.Model):
    """One user's connected Gmail mailbox.

    Replaces the single shared token file: each user connects their own
    mailbox on the integrations page and the sync crawls every account.
    The matter contract is the label NAME (``Matter.gmail_label_name``);
    each account resolves that name to its own label id at sync time, so
    staff just create the same labels under GMAIL_LABEL_ROOT.
    """

    user = models.OneToOneField(
        "accounts.CustomUser", on_delete=models.CASCADE, related_name="gmail_account"
    )
    # The mailbox's own address (users.getProfile at connect time) — also
    # how sent mail is recognized for "To: X" display.
    address = models.EmailField()
    # Authorized-user credentials JSON (what the token file used to hold).
    token = models.TextField()
    # Per-account History-API cursor; empty triggers a bootstrap for this
    # account only. A stale cursor (HTTP 404) clears it, same as before.
    history_id = models.CharField(max_length=32, null=True, blank=True)
    # Matter label names this mailbox has no label for — surfaced on the
    # integrations page so staff know which labels to create where.
    missing_labels = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sync_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.address or f"Gmail account {self.pk}"

    @property
    def can_manage_labels(self):
        """True when the stored token carries the gmail.labels scope.

        Connects that predate automatic label setup were read-only; the
        integrations page nudges those users to reconnect.
        """
        try:
            scopes = json.loads(self.token).get("scopes") or []
        except (TypeError, ValueError):
            return False
        return GMAIL_LABELS_SCOPE in scopes

    class Meta:
        db_table = "app_gmail_account"


class EmailQuerySet(models.QuerySet):
    def dedup(self):
        """Collapse cross-mailbox duplicates of the same message.

        Keeps the first-synced row per (matter, message_id); rows with no
        Message-ID header always pass. The winner is chosen among ALL of the
        matter's rows (not just this queryset's filter), so the visible row
        for a message is stable regardless of active filters.
        """
        first = (
            self.model.objects.filter(
                matter=models.OuterRef("matter"),
                message_id=models.OuterRef("message_id"),
            )
            .order_by("synced_at", "id")
            .values("id")[:1]
        )
        return self.filter(
            models.Q(message_id="") | models.Q(id=models.Subquery(first))
        )


class Email(AuditMixin, models.Model):
    """A Gmail message synced onto a matter via its mapped Gmail label.

    Text-only record: Gmail remains the archive of record and ``gmail_id``
    deep-links back to the original message. Attachments are recorded as
    metadata only (never fetched). Rows are immutable once synced — the sync
    skips existing (account, matter, gmail_id) pairs so ``updated_at`` stays
    honest for the auto-summary's ``since=`` incremental filtering.

    One row per (account, matter): the same message labeled in two mailboxes
    yields two rows (provenance — unlabeling in one mailbox only drops that
    account's row), collapsed for display/AI by ``message_id`` via
    ``Email.objects.dedup_for_matter`` (first-synced wins).
    """

    matter = models.ForeignKey(
        "matters.Matter", on_delete=models.CASCADE, related_name="emails"
    )
    # The mailbox this row was synced from. Nullable only for pre-multi-
    # account rows awaiting the adopt_gmail_account command; the sync always
    # sets it. Deleting an account drops that mailbox's view of the mail.
    account = models.ForeignKey(
        GmailAccount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="emails",
    )
    gmail_id = models.CharField(max_length=32)
    # RFC-822 Message-ID header — the cross-mailbox identity used to collapse
    # duplicates. Blank when the message has no header (rare); such rows are
    # never collapsed.
    message_id = models.CharField(max_length=998, blank=True, db_index=True)
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
    # Raw HTML part when the message has one — drives the preview pane and
    # promoted-PDF rendering; body_text stays canonical for AI context/search.
    body_html = models.TextField(blank=True)
    BODY_SOURCE_CHOICES = [("plain", "Plain text"), ("html", "HTML")]
    body_source = models.CharField(
        max_length=10, choices=BODY_SOURCE_CHOICES, default="plain"
    )
    # Email is voluminous and mostly supporting material, so it defaults a
    # notch below Documents/Notes (4).
    importance = models.PositiveIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    ai_context = models.CharField(
        max_length=6, choices=AI_CONTEXT_CHOICES, default="auto"
    )
    # Set when the email is promoted to a Document (PDF rendered into the
    # matter's record). The Document owns highlights and survives any sync
    # removal of this row; promotion also flips ai_context to "never" so the
    # content isn't fed to the AI twice.
    document = models.ForeignKey(
        "case.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_emails",
    )
    synced_at = models.DateTimeField(default=timezone.now)

    objects = EmailQuerySet.as_manager()

    def __str__(self):
        return f"{self.subject or '(no subject)'} — {self.sender}"

    @property
    def gmail_url(self):
        # /u/<address> routes to the right mailbox for whoever is signed in
        # to it; /u/0 is the pre-multi-account fallback.
        mailbox = self.account.address if self.account_id and self.account else "0"
        return f"https://mail.google.com/mail/u/{mailbox}/#all/{self.gmail_id}"

    @property
    def is_sent(self):
        """True when this row's mailbox sent the message."""
        from email.utils import parseaddr

        if not (self.account_id and self.account and self.account.address):
            return False
        return parseaddr(self.sender or "")[1].lower() == self.account.address.lower()

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
            # it is context for both cases. Per account: two mailboxes each
            # holding the message yield one row each (dedup collapses them
            # for display). NULL accounts (pre-adoption rows) fall outside
            # the constraint; the adopt command assigns them.
            models.UniqueConstraint(
                fields=["account", "matter", "gmail_id"],
                name="unique_email_per_account_matter",
            )
        ]
        indexes = [models.Index(fields=["matter", "thread_id"])]


class EmailAttachment(models.Model):
    """Attachment metadata plus extracted text (the binary stays in Gmail).

    ``gmail_attachment_id`` lets the extraction task fetch the bytes on
    demand; supported types get their text stored here and fed into the
    email's AI-context thread. Never fetched for display — Gmail remains the
    archive for the file itself.
    """

    EXTRACT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("extracted", "Extracted"),
        ("no_text_layer", "No text layer (scanned)"),
        ("unsupported", "Unsupported type"),
        ("failed", "Failed"),
    ]

    email = models.ForeignKey(
        Email, on_delete=models.CASCADE, related_name="attachment_files"
    )
    # Gmail attachment ids routinely exceed 200 characters.
    gmail_attachment_id = models.TextField(blank=True)
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    text = models.TextField(blank=True)
    extract_status = models.CharField(
        max_length=15, choices=EXTRACT_STATUS_CHOICES, default="pending"
    )

    def __str__(self):
        return self.filename

    class Meta:
        db_table = "app_email_attachment"
        ordering = ["id"]


class GmailSyncState(models.Model):
    """LEGACY single-mailbox sync cursor.

    Superseded by ``GmailAccount.history_id`` (one cursor per mailbox); kept
    only so ``adopt_gmail_account`` can carry the cursor over. Remove the
    model once adoption has run on prod.
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
