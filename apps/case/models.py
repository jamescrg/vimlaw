from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.case.abbreviate import bluebook_abbreviate
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from utils.models import AuditMixin

User = get_user_model()


class Label(AuditMixin, models.Model):
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
    history = HistoricalRecords()

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


class Document(AuditMixin, models.Model):
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
    history = HistoricalRecords()

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
        ordering = ["-created_at"]
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


class Highlight(AuditMixin, models.Model):
    """Text highlight/annotation on a document or case law."""

    # Source - one of document or caselaw must be set
    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        related_name="highlights",
        null=True,
        blank=True,
    )
    caselaw = models.ForeignKey(
        "CaseLaw",
        on_delete=models.CASCADE,
        related_name="highlights",
        null=True,
        blank=True,
    )

    slug = models.CharField(max_length=255)
    text = models.TextField()  # Captured highlight text for search
    page_number = models.PositiveIntegerField(null=True, blank=True)
    paragraph_number = models.CharField(max_length=20, blank=True, null=True)

    # PDF coordinates (for document highlights only)
    # {"rects": [{"x1": float, "y1": float, "x2": float, "y2": float}, ...]}
    coordinates = models.JSONField(null=True, blank=True)

    # Text locator for case law highlights (character offset from start)
    char_offset = models.PositiveIntegerField(null=True, blank=True)

    COLOR_CHOICES = [
        ("yellow", "Yellow"),
        ("green", "Green"),
        ("blue", "Blue"),
        ("orange", "Orange"),
        ("red", "Red"),
        ("purple", "Purple"),
    ]
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default="yellow")

    # Full-text search
    search_vector = SearchVectorField(null=True, blank=True)

    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    labels = models.ManyToManyField(Label, related_name="highlights", blank=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "app_document_highlight"
        ordering = ["created_at"]
        indexes = [
            GinIndex(fields=["search_vector"]),
            models.Index(fields=["document", "page_number"]),
            models.Index(fields=["caselaw", "char_offset"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(document__isnull=False, caselaw__isnull=True)
                    | models.Q(document__isnull=True, caselaw__isnull=False)
                ),
                name="highlight_has_one_source",
            )
        ]

    def __str__(self):
        if self.document:
            return f"{self.slug} - Page {self.page_number}"
        elif self.caselaw:
            return f"{self.slug} - {self.caselaw.citation}"
        return self.slug

    @property
    def source(self):
        """Return the source object (document or caselaw)."""
        return self.document or self.caselaw

    @property
    def source_type(self):
        """Return 'document' or 'caselaw'."""
        if self.document:
            return "document"
        return "caselaw"

    @property
    def citation(self):
        """Return citation for either document or case law source."""
        if self.document:
            doc_citation = self.document.citation
            # Remove closing ")" to insert location, keeping the period
            # Format with paragraph: (Abbrev. ¶ 5.)
            # Format with page: (Abbrev. at 5.)
            base = doc_citation[:-1]  # Remove closing ")" only
            if self.paragraph_number:
                para = self.paragraph_number.rstrip(".")
                return f"{base} ¶ {para}.)"
            return f"{base} at {self.page_number}.)"
        elif self.caselaw:
            # Case law citation format: Abbreviated Name, Vol. Rep. Page, Pin (Year)
            from apps.case.abbreviate import abbreviate_case_name

            case_name = abbreviate_case_name(self.caselaw.case_name)
            reporter_cite = self.caselaw.citation

            if self.page_number:
                import re

                # Find first page number (digits followed by comma, space, or paren)
                # Pattern: volume reporter page -> insert pin after page
                match = re.search(r"(\d+\s+[A-Za-z.\s]+\d+)(,|\s+\()", reporter_cite)
                if match:
                    # Insert pin cite after first page number
                    insert_pos = match.end(1)
                    reporter_cite = (
                        f"{reporter_cite[:insert_pos]}, "
                        f"{self.page_number}{reporter_cite[insert_pos:]}"
                    )
            return f"{case_name}, {reporter_cite}."
        return ""


class Fact(AuditMixin, models.Model):
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
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_fact"


class Witness(AuditMixin, models.Model):
    """Witness associated with a matter."""

    ALIGNMENT_CHOICES = [
        ("friendly", "Friendly"),
        ("neutral", "Neutral"),
        ("hostile", "Hostile"),
    ]

    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="witnesses"
    )
    name = models.CharField(max_length=255)
    affiliation = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    alignment = models.CharField(
        max_length=20, choices=ALIGNMENT_CHOICES, default="neutral"
    )
    knowledge = models.TextField(blank=True)
    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_witness"
        ordering = ["name"]


class CaseLaw(AuditMixin, models.Model):
    """A case law opinion retrieved from CourtListener."""

    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="case_laws"
    )

    # Citation info
    citation = models.CharField(max_length=255)  # e.g., "410 U.S. 113"
    case_name = models.CharField(max_length=500)  # e.g., "Roe v. Wade"

    # Court/date info
    court = models.CharField(max_length=255)  # Full court name
    court_id = models.CharField(max_length=50, blank=True)  # CourtListener court ID
    date_filed = models.DateField(null=True, blank=True)
    docket_number = models.CharField(max_length=255, blank=True)

    # CourtListener IDs for future reference
    cluster_id = models.IntegerField(null=True, blank=True)
    opinion_id = models.IntegerField(null=True, blank=True)
    courtlistener_url = models.URLField(max_length=500, blank=True)

    # Full text
    text = models.TextField()  # Plain text version
    html = models.TextField(blank=True)  # HTML with citations (optional)

    # User notes and importance
    notes = models.TextField(blank=True)
    importance = models.IntegerField(default=5)  # 1-10, like documents

    # AI context - determines if case full text is submitted to AI conversations
    include_in_ai = models.BooleanField(default=False)

    # Labels (like other case app models)
    labels = models.ManyToManyField(Label, blank=True, related_name="case_laws")

    history = HistoricalRecords()

    def __str__(self):
        return f"{self.case_name}, {self.citation}"

    @property
    def page_count(self):
        """Compute page count from star-pagination markers in HTML."""
        import re

        if not self.html:
            return None
        # Count star-pagination spans: <span class="star-pagination">*123</span>
        matches = re.findall(r'class="star-pagination"', self.html)
        return len(matches) if matches else None

    class Meta:
        db_table = "app_case_law"
        ordering = ["-date_filed", "case_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["matter", "cluster_id"],
                name="unique_case_per_matter",
                condition=models.Q(cluster_id__isnull=False),
            )
        ]
