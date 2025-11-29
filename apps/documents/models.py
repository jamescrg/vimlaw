from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

User = get_user_model()


class Label(models.Model):
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#FFFFFF")  # Hex color code

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_label"
        ordering = ["name"]


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

    def __str__(self):
        return self.name

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

        # Set category to "Record" if proceeding is set
        if self.proceeding and self.category != "Record":
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

    class Meta:
        db_table = "app_document_highlight"
        ordering = ["document", "page_number", "created_at"]
        indexes = [
            GinIndex(fields=["search_vector"]),
            models.Index(fields=["document", "page_number"]),
        ]

    def __str__(self):
        return f"{self.slug} - Page {self.page_number}"
