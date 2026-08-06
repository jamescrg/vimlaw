"""Draft links: a case AI conversation pinned to one Drive ODT.

The drafting workflow is companion-first: the user opens the document in
LibreOffice (the local Drive copy, synced by Insync or similar), installs
the Kosmos companion extension, and links the conversation to the file from
the chat window. AI-proposed edits are queued as CompanionRounds and applied
to the live document as tracked changes; the extension pushes the document
back so doc_text stays current. There is no server-side working copy, no
version chain, and no publish step: the document in Writer is the working
copy, Ctrl+Z is version control, and saving the file (which syncs to Drive)
is publishing.

Conversation is imported for the class (not a string label): it lives in
apps/case/ai/models.py, which is NOT loaded by apps.case's models.py, so a
lazy 'case.Conversation' reference only resolves if something else has
imported that module first.
"""

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.case.ai.models import Conversation

# A companion counts as connected while its last poll is this recent. The
# extension polls every ~2.5 seconds, so this tolerates a few missed cycles
# without leaving a closed LibreOffice "connected" for long.
COMPANION_WINDOW_SECONDS = 15


def draft_file_path(instance, filename):  # pragma: no cover
    """Retired with DraftVersion; kept because migration 0001 imports it."""
    raise NotImplementedError("DraftVersion was removed in migration 0003")


class DraftLink(models.Model):
    """Pins one conversation to one Drive ODT ("the draft").

    doc_text is the Markdown facsimile the AI reads: snapshotted from Drive
    at link time, then overwritten by every companion push, so it tracks the
    document as the user last had it (hand edits included).
    """

    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name="draft_link"
    )
    drive_file_id = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    doc_text = models.TextField(blank=True)
    doc_text_at = models.DateTimeField(null=True, blank=True)
    companion_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.conversation.title})"

    @property
    def matter(self):
        return self.conversation.matter

    @property
    def companion_active(self):
        return bool(
            self.companion_seen
            and timezone.now() - self.companion_seen
            < timedelta(seconds=COMPANION_WINDOW_SECONDS)
        )


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
    edits to the live document, and posts the outcome back. Rounds are the
    lasting record of what the AI changed and when.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("applied", "Applied"),
        ("failed", "Failed"),
        ("expired", "Expired"),
    ]

    link = models.ForeignKey(DraftLink, on_delete=models.CASCADE, related_name="rounds")
    # Wire-form edit dicts (see apps.drive.redline.edit_to_dict).
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
        return f"Round {self.id} for link {self.link_id} ({self.status})"
