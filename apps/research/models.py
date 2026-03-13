from django.db import models

from utils.models import AuditMixin

STATUS_CHOICES = [
    ("pending", "Pending"),
    ("refining", "Refining"),
    ("refined", "Refined"),
    ("searching", "Searching"),
    ("processing", "Processing"),
    ("complete", "Complete"),
    ("error", "Error"),
]

RELEVANCE_CHOICES = [
    ("pending", "Pending"),
    ("high", "High"),
    ("medium", "Medium"),
    ("low", "Low"),
    ("error", "Error"),
]


class ResearchQuery(AuditMixin):
    query_text = models.TextField()
    state = models.CharField(max_length=20, blank=True, default="")
    include_federal = models.BooleanField(default=False)
    structured_query = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    final_summary = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Research: {self.query_text[:50]}"

    @property
    def jurisdiction_display(self):
        from .jurisdictions import get_state_display

        if not self.state:
            return "All Jurisdictions"
        label = get_state_display(self.state)
        return f"{label} + Federal" if self.include_federal else label


VERIFY_STATUS_CHOICES = [
    ("none", "None"),
    ("verifying", "Verifying"),
    ("complete", "Complete"),
    ("error", "Error"),
]


class ResearchResult(AuditMixin):
    query = models.ForeignKey(
        ResearchQuery, on_delete=models.CASCADE, related_name="results"
    )
    position = models.PositiveSmallIntegerField()
    case_name = models.CharField(max_length=500, blank=True, default="")
    citation = models.CharField(max_length=300, blank=True, default="")
    court = models.CharField(max_length=200, blank=True, default="")
    date_filed = models.CharField(max_length=20, blank=True, default="")
    cluster_id = models.IntegerField(null=True, blank=True)
    snippet = models.TextField(blank=True, default="")
    score = models.FloatField(null=True, blank=True)
    courtlistener_url = models.URLField(max_length=500, blank=True, default="")
    opinion_text = models.TextField(blank=True, default="")
    relevance = models.CharField(
        max_length=20, choices=RELEVANCE_CHOICES, default="pending"
    )
    gemini_summary = models.TextField(blank=True, default="")
    status_message = models.CharField(max_length=200, blank=True, default="")
    forward_citation_count = models.IntegerField(null=True, blank=True)
    verify_status = models.CharField(
        max_length=20, choices=VERIFY_STATUS_CHOICES, default="none"
    )

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"Result {self.position}: {self.case_name[:50]}"


class CitationVerification(AuditMixin):
    result = models.ForeignKey(
        ResearchResult, on_delete=models.CASCADE, related_name="verifications"
    )
    position = models.PositiveSmallIntegerField()
    case_name = models.CharField(max_length=500, blank=True, default="")
    citation = models.CharField(max_length=300, blank=True, default="")
    court = models.CharField(max_length=200, blank=True, default="")
    date_filed = models.CharField(max_length=20, blank=True, default="")
    cluster_id = models.IntegerField(null=True, blank=True)
    courtlistener_url = models.URLField(max_length=500, blank=True, default="")
    depth = models.IntegerField(default=0)
    summary = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"Verification {self.position}: {self.case_name[:50]}"
