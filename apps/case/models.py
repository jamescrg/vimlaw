from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.case.abbreviate import bluebook_abbreviate
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

User = get_user_model()


class Label(models.Model):
    COLOR_CHOICES = [
        ("blue", "Blue"),
        ("gray", "Gray"),
        ("green", "Green"),
        ("orange", "Orange"),
        ("purple", "Purple"),
        ("red", "Red"),
        ("yellow", "Yellow"),
    ]

    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="labels", null=True, blank=True
    )
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default="gray")

    def __str__(self):
        return self.name

    @property
    def is_global(self):
        return self.matter is None

    class Meta:
        db_table = "app_label"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["matter", "name"], name="unique_label_per_matter"
            )
        ]


def document_upload_path(instance, filename):
    """Generate simple ID-based storage path: documents/{matter_id}/{document_id}.{ext}"""
    file_extension = filename.split(".")[-1].lower()
    return f"documents/{instance.matter_id}/{instance.pk}.{file_extension}"


class Document(models.Model):
    CATEGORY_CHOICES = [
        ("Correspondence", "Correspondence"),
        ("Discovery", "Discovery"),
        ("Evidence", "Evidence"),
        ("Record", "Record"),
    ]

    OCR_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("extracted", "Extracted"),
        ("failed", "Failed"),
        ("not_applicable", "Not Applicable"),
    ]

    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="documents"
    )
    date = models.DateField(blank=True, null=True)
    name = models.CharField(max_length=255)
    abbreviated_name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default="Evidence",
    )
    proceeding = models.ForeignKey(
        Proceeding, on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(upload_to=document_upload_path, max_length=500)
    labels = models.ManyToManyField(Label, related_name="documents", blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # OCR fields
    ocr_status = models.CharField(
        max_length=20, choices=OCR_STATUS_CHOICES, default="pending"
    )
    ocr_text = models.TextField(blank=True, null=True)
    ocr_error = models.TextField(blank=True, null=True)
    ocr_processed_at = models.DateTimeField(blank=True, null=True)
    page_count = models.PositiveIntegerField(blank=True, null=True)
    ocr_pages_done = models.PositiveIntegerField(default=0)

    # Full-text search
    search_vector = SearchVectorField(null=True, blank=True)

    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )

    def __str__(self):
        return self.name

    @property
    def citation(self):
        """Return abbreviated name for citation, using manual override or auto-generated."""
        if self.abbreviated_name:
            abbrev = self.abbreviated_name
        else:
            abbrev = bluebook_abbreviate(self.name)
        # Ensure it ends with a period (but don't double up)
        if not abbrev.endswith("."):
            abbrev = abbrev + "."
        return f"({abbrev})"

    class Meta:
        db_table = "app_document"
        ordering = ["-uploaded_at"]
        indexes = [
            GinIndex(fields=["search_vector"]),
        ]

    def save(self, *args, **kwargs):
        # Exclude file from validation during two-phase save (first save has no file)
        exclude = ["file"] if not self.file else []
        self.full_clean(exclude=exclude)

        # Set category to "Record" if proceeding is set (unless Discovery)
        if self.proceeding and self.category not in ("Record", "Discovery"):
            self.category = "Record"

        super().save(*args, **kwargs)


class Highlight(models.Model):
    """Text highlight/annotation on a document."""

    document = models.ForeignKey(
        "Document", on_delete=models.CASCADE, related_name="highlights"
    )
    slug = models.CharField(max_length=255)
    text = models.TextField()  # Captured highlight text for search
    page_number = models.PositiveIntegerField()
    paragraph_number = models.CharField(max_length=20, blank=True, null=True)
    # {"rects": [{"x1": float, "y1": float, "x2": float, "y2": float}, ...]}
    coordinates = models.JSONField()
    COLOR_CHOICES = [
        ("yellow", "Yellow"),
        ("green", "Green"),
        ("blue", "Blue"),
        ("orange", "Orange"),
        ("red", "Red"),
        ("purple", "Purple"),
    ]
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default="yellow")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Full-text search
    search_vector = SearchVectorField(null=True, blank=True)

    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    labels = models.ManyToManyField(Label, related_name="highlights", blank=True)

    class Meta:
        db_table = "app_document_highlight"
        ordering = ["document", "page_number", "created_at"]
        indexes = [
            GinIndex(fields=["search_vector"]),
            models.Index(fields=["document", "page_number"]),
        ]

    def __str__(self):
        return f"{self.slug} - Page {self.page_number}"

    @property
    def citation(self):
        """Return citation with document abbreviation and page/paragraph number."""
        doc_citation = self.document.citation
        # Remove closing ")" to insert location, keeping the period
        # Format with paragraph: (Abbrev. ¶ 5.)
        # Format with page: (Abbrev. at 5.)
        base = doc_citation[:-1]  # Remove closing ")" only
        if self.paragraph_number:
            return f"{base} ¶ {self.paragraph_number}.)"
        return f"{base} at {self.page_number}.)"


class Fact(models.Model):
    """Timeline fact/event for a matter."""

    COLOR_CHOICES = [
        (None, "None"),
        ("Blue", "Blue"),
        ("Gray", "Gray"),
        ("Green", "Green"),
        ("Orange", "Orange"),
        ("Purple", "Purple"),
        ("Red", "Red"),
        ("Yellow", "Yellow"),
    ]

    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    description = models.CharField(max_length=150, null=True)
    color = models.CharField(
        max_length=10, choices=COLOR_CHOICES, blank=True, null=True, default=None
    )

    # Source references
    documents = models.ManyToManyField("Document", blank=True, related_name="facts")
    highlights = models.ManyToManyField("Highlight", blank=True, related_name="facts")

    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    labels = models.ManyToManyField(Label, related_name="facts", blank=True)

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_fact"


class Note(models.Model):
    """Rich markdown note for a matter with inline document/highlight references."""

    CATEGORY_CHOICES = [
        ("analysis", "Analysis"),
        ("drafting", "Drafting"),
        ("interview", "Interview"),
        ("issue", "Issue"),
        ("note", "Note"),
    ]

    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="case_notes",
    )
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, related_name="notes")
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="note")
    date = models.DateField(default=timezone.localdate)
    content = models.TextField(blank=True, default="")  # Markdown content

    # Source references (tracked separately from inline [[doc:id]] syntax)
    documents = models.ManyToManyField("Document", blank=True, related_name="notes")
    highlights = models.ManyToManyField("Highlight", blank=True, related_name="notes")

    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    viewed_at = models.DateTimeField(null=True, blank=True)
    labels = models.ManyToManyField(Label, related_name="notes", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        db_table = "app_note"
        ordering = ["-updated_at"]
