from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin

User = get_user_model()


class NoteFolder(AuditMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=50)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="note_folders",
        help_text="Null = general tree; set = this matter's private tree",
    )
    depth = models.IntegerField(default=0)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_note_folder"
        ordering = ["name"]

    def get_ancestors(self):
        """Walk parent chain, return list from root to immediate parent."""
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        ancestors.reverse()
        return ancestors

    def get_descendants(self):
        """Recursively collect all children."""
        descendants = []
        for child in self.children.all():
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants

    def can_have_children(self):
        return self.depth < 3

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.parent_id is not None:
            if self.parent_id == self.pk:
                raise ValidationError("A folder cannot be its own parent.")
            if self.parent.matter_id != self.matter_id:
                raise ValidationError(
                    "A folder must belong to the same matter as its parent."
                )
            if self.parent.depth >= 3:
                raise ValidationError("Maximum folder depth (4 levels) exceeded.")
            # Check for circular reference
            current = self.parent
            while current is not None:
                if current.pk == self.pk:
                    raise ValidationError("Circular folder reference detected.")
                current = current.parent
            self.depth = self.parent.depth + 1
        else:
            self.depth = 0

    def save(self, *args, **kwargs):
        if not kwargs.get("update_fields"):
            self.full_clean()
        super().save(*args, **kwargs)

    def update_descendant_depths(self):
        """Recursively fix child depths after a move."""
        for child in self.children.all():
            child.depth = self.depth + 1
            child.save(update_fields=["depth"])
            child.update_descendant_depths()


def get_library_notes():
    """Every standalone note: the whole Library tree feeds the AI.

    Notes carry no AI knobs — library notes are all selectable, matter
    notes are all selectable for their matter, and force-inclusion is
    copy-paste into the chat.
    """
    return Note.objects.filter(matter__isnull=True)


class Note(AuditMixin, models.Model):
    """Rich markdown note for a matter with inline document/highlight references."""

    CATEGORY_CHOICES = [
        ("analysis", "Analysis"),
        ("drafting", "Drafting"),
        ("guide", "Guide"),
        ("interview", "Interview"),
        ("issue", "Issue"),
        ("note", "Note"),
        ("research", "Research"),
    ]

    author = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_notes",
    )
    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="notes", null=True, blank=True
    )
    # INVARIANT: folder is None, or folder.matter_id == self.matter_id — a
    # note never files into another matter's (or the general) tree. Enforced
    # at the view layer (validate_folder_move, note_move) because every move
    # path saves with update_fields, which skips full_clean.
    folder = models.ForeignKey(
        NoteFolder, on_delete=models.SET_NULL, blank=True, null=True
    )
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="note")
    topic = models.CharField(max_length=255, blank=True, null=True)
    content = models.TextField(blank=True, default="")  # Markdown content

    # Source references (tracked separately from inline [[doc:id]] syntax)
    documents = models.ManyToManyField(
        "case.Document", blank=True, related_name="notes"
    )
    highlights = models.ManyToManyField(
        "case.Highlight", blank=True, related_name="notes"
    )

    importance = models.PositiveIntegerField(default=4)
    summary = models.TextField(
        blank=True,
        default="",
        help_text="AI-generated abstract used for intelligent context selection",
    )
    # md5 of the content excerpt the summary was generated from; a mismatch
    # marks the summary stale without touching updated_at on metadata saves.
    summary_source_hash = models.CharField(max_length=32, blank=True, default="")
    labels = models.ManyToManyField("case.Label", related_name="notes", blank=True)

    viewed_at = models.DateTimeField(null=True, blank=True)
    # Editor toolbar toggle: Claude Desktop (the MCP notes API) may write
    # to this note until this time; null = no external write access. The
    # in-app AI's note writes are not gated by this.
    ai_write_until = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.title

    class Meta:
        db_table = "app_note"
        ordering = ["-updated_at"]


class NoteView(models.Model):
    """Tracks when each user last viewed each note."""

    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="note_views",
    )
    note = models.ForeignKey(
        Note,
        on_delete=models.CASCADE,
        related_name="views",
    )
    created_at = models.DateTimeField(default=timezone.now)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_note_view"
        unique_together = ("user", "note")
        ordering = ["-viewed_at"]

    def __str__(self):
        return f"{self.user} viewed {self.note} at {self.viewed_at}"
