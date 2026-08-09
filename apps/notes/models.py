from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin

User = get_user_model()

# AI context inclusion modes (mirrors apps.case.models.AI_CONTEXT_CHOICES).
AI_CONTEXT_CHOICES = [
    ("auto", "Auto"),
    ("always", "Always"),
    ("never", "Never"),
]


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
    depth = models.IntegerField(default=0)
    ai_library = models.BooleanField(
        default=False,
        help_text="Notes in this folder and its subfolders are offered to the matter AI",
    )
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    @property
    def in_ai_library(self):
        """True when this folder or any ancestor is flagged as AI library."""
        if self.ai_library:
            return True
        return any(a.ai_library for a in self.get_ancestors())

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


def library_folder_ids():
    """Ids of AI-library folders: every flagged folder plus all descendants."""
    folders = list(NoteFolder.objects.only("id", "parent_id", "ai_library"))
    children = {}
    for f in folders:
        children.setdefault(f.parent_id, []).append(f)
    ids = set()

    def mark(folder):
        if folder.id in ids:
            return
        ids.add(folder.id)
        for child in children.get(folder.id, []):
            mark(child)

    for f in folders:
        if f.ai_library:
            mark(f)
    return ids


def get_library_notes():
    """Standalone notes eligible for the AI library (folder opt-in, not never)."""
    return Note.objects.filter(
        matter__isnull=True, folder_id__in=library_folder_ids()
    ).exclude(ai_context="never")


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
    ai_context = models.CharField(
        max_length=6,
        choices=AI_CONTEXT_CHOICES,
        default="auto",
        help_text="AI context inclusion: auto (selector decides), always, or never",
    )
    summary = models.TextField(
        blank=True,
        default="",
        help_text="AI-generated abstract used for intelligent context selection",
    )
    # md5 of the content excerpt the summary was generated from; a mismatch
    # marks the summary stale without touching updated_at on metadata saves.
    summary_source_hash = models.CharField(max_length=32, blank=True, default="")
    labels = models.ManyToManyField("case.Label", related_name="notes", blank=True)

    # Google Drive sync provenance — null for user-authored notes. A synced note
    # is upserted by drive_file_id; drive_modified is the freshness marker used
    # to skip unchanged files. Content history is tracked via HistoricalRecords.
    drive_file_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    drive_path = models.CharField(max_length=1024, null=True, blank=True)
    drive_modified = models.CharField(max_length=64, null=True, blank=True)
    drive_synced_at = models.DateTimeField(null=True, blank=True)

    viewed_at = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.title

    @property
    def is_synced(self):
        """True if this note is mirrored from Google Drive (read-only in-app)."""
        return bool(self.drive_file_id)

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
