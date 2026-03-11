from django.db import models

from utils.models import AuditMixin

STATUS_CHOICES = [
    ("pending", "Pending"),
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
    jurisdiction = models.CharField(max_length=100, blank=True, default="")
    jurisdiction_display = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    final_summary = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Research: {self.query_text[:50]}"


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

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"Result {self.position}: {self.case_name[:50]}"
