from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from utils.models import AuditMixin


class Conversation(AuditMixin, models.Model):
    """A chat conversation within a matter context."""

    LLM_CHOICES = [
        ("claude", "Claude"),
        ("gemini-flash", "Gemini Flash"),
        ("gemini-pro", "Gemini Pro"),
    ]

    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="ai_conversations"
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_conversations",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    llm = models.CharField(max_length=20, choices=LLM_CHOICES, default="claude")
    history = HistoricalRecords()

    class Meta:
        ordering = ["-updated_at"]
        db_table = "matters_conversation"  # Keep same table name

    def save(self, *args, **kwargs):
        if self.title:
            self.title = self.title[0].upper() + self.title[1:]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.matter.name} - {self.title or 'Untitled'}"

    def get_participants(self):
        """Return distinct users who have sent messages in this conversation."""
        return CustomUser.objects.filter(ai_messages__conversation=self).distinct()


class Message(AuditMixin, models.Model):
    """Individual message in a conversation."""

    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()

    # Track which user sent this message (null for assistant messages)
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_messages",
    )

    # Track token usage for monitoring
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["created_at"]
        db_table = "matters_message"  # Keep same table name

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


class ChatAttachment(AuditMixin, models.Model):
    """File attachment for a chat conversation (temporary context, not saved to documents)."""

    OCR_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to="chat_attachments/")
    filename = models.CharField(max_length=255)
    ocr_text = models.TextField(blank=True)
    ocr_status = models.CharField(
        max_length=20, choices=OCR_STATUS_CHOICES, default="pending"
    )
    history = HistoricalRecords()

    class Meta:
        ordering = ["created_at"]
        db_table = "matters_chat_attachment"

    def __str__(self):
        return f"{self.filename} ({self.ocr_status})"
