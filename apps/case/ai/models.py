from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.case.models import AI_CONTEXT_CHOICES
from apps.matters.models import Matter
from utils.models import AuditMixin


class Conversation(AuditMixin, models.Model):
    """A chat conversation within a matter context."""

    # Note: "claude" (Sonnet 4.6) and "gemini-pro" (Gemini 2.5 Pro) were
    # retired from the picker but remain supported in the dispatch/selector
    # plumbing so existing conversations on those models keep working.
    LLM_CHOICES = [
        ("claude-opus", "Claude Opus 4.8"),
        ("claude-opus-4-6", "Claude Opus 4.6"),
        ("gemini-flash", "Gemini 2.5 Flash"),
        ("gemini-pro-latest", "Gemini Pro (Latest)"),
    ]

    # Chat modes: "classic" (shown as Analysis) is the original
    # single-completion chat; "research" runs an agentic CourtListener tool
    # loop (searches, reads opinions, cites only what it retrieved). The
    # mode is picked per turn via the chat-header dropdown; `kind` holds
    # the mode of the latest turn (and the default for the next one).
    KIND_CHOICES = [
        ("classic", "Analysis"),
        ("research", "Research"),
    ]
    EFFORT_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    # A conversation belongs to exactly one of: a matter (case chat), an
    # intake (intake chat), or an agenda user (the dash agenda chat).
    # Intake and agenda conversations are ephemeral: at most one live per
    # owner, deleted on end/discard.
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
        null=True,
        blank=True,
    )
    intake = models.ForeignKey(
        "intakes.Intake",
        on_delete=models.CASCADE,
        related_name="ai_conversations",
        null=True,
        blank=True,
    )
    agenda_user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="agenda_conversations",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_conversations",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    llm = models.CharField(
        max_length=20, choices=LLM_CHOICES, default="gemini-pro-latest"
    )
    ai_context = models.CharField(
        max_length=6,
        choices=AI_CONTEXT_CHOICES,
        default="auto",
        help_text="AI context inclusion: auto (selector decides), always, or never",
    )
    summary = models.TextField(
        blank=True,
        null=True,
        help_text="AI-generated summary for intelligent context selection",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="classic")
    # How hard each turn works, in both modes. Research: the tool-call
    # budget (high also plans before searching). Analysis: the context
    # apparatus (low skips the selector and loads no material bodies; high
    # re-selects every turn with a stronger selector model). Formerly
    # research_depth quick/standard/deep (remapped in 0075), then
    # research_effort (renamed in 0076 when Analysis gained effort too).
    effort = models.CharField(max_length=10, choices=EFFORT_CHOICES, default="medium")
    vet_citations = models.BooleanField(
        default=True,
        help_text=(
            "After each response, launch a Gemini Flash job per cited case to "
            "check whether the case actually supports what the AI claims."
        ),
    )
    history = HistoricalRecords()

    class Meta:
        ordering = ["-created_at", "-id"]
        db_table = "matters_conversation"  # Keep same table name

    def save(self, *args, **kwargs):
        if self.title:
            self.title = self.title[0].upper() + self.title[1:]
        super().save(*args, **kwargs)

    def __str__(self):
        if self.matter_id:
            owner = self.matter.name
        elif self.intake_id:
            owner = self.intake.name
        elif self.agenda_user_id:
            owner = f"Agenda - {self.agenda_user.username}"
        else:
            owner = "Unattached"
        return f"{owner} - {self.title or 'Untitled'}"

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

    # Verified citations for assistant messages
    verified_citations = models.JSONField(default=list, blank=True)

    # Research-kind assistant messages: the research trail (plan, searches,
    # opinions read, treatment checks) rendered as a collapsible section.
    research_trail = models.JSONField(default=list, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["created_at"]
        db_table = "matters_message"  # Keep same table name

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
