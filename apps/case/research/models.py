from django.db import models

from utils.models import AuditMixin

STATUS_CHOICES = [
    ("pending", "Pending"),
    ("refining", "Refining"),
    ("refined", "Refined"),
    ("searching", "Searching"),
    ("processing", "Processing"),
    ("enriching", "Enriching"),
    ("synthesizing", "Synthesizing"),
    ("complete", "Complete"),
    ("error", "Error"),
]

RELEVANCE_CHOICES = [
    ("none", "Not assessed"),
    ("pending", "Pending"),
    ("high", "High"),
    ("medium", "Medium"),
    ("low", "Low"),
    ("rejected", "Ruled out at triage"),
    ("error", "Error"),
]

# How a result entered the run: the relevance-ranked search, the
# newest-first slice of the same query, a forward-citation search from a
# strong case, or a backward chase of an authority a brief relied on.
SOURCE_CHOICES = [
    ("search", "Search"),
    ("date", "Recent"),
    ("citing", "Citing case"),
    ("authority", "Cited authority"),
]


class ResearchQuery(AuditMixin):
    matter = models.ForeignKey(
        "matters.Matter",
        on_delete=models.CASCADE,
        related_name="research_queries",
    )
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
        max_length=20, choices=RELEVANCE_CHOICES, default="none"
    )
    gemini_summary = models.TextField(blank=True, default="")
    # Full structured abstract (CASE/POSTURE/VEHICLE/HOLDING/...); replaces
    # gemini_summary on new runs, which stays populated on legacy rows.
    brief = models.TextField(blank=True, default="")
    # Triage rejection reason, or the brief's relevance rationale - kept so
    # ruled-out rows stay debuggable instead of vanishing.
    eval_reason = models.TextField(blank=True, default="")
    # Reporter citations the brief says the holding rests on (chase seeds).
    key_authorities = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="search")
    # The case that led here, for citing/authority rows.
    via_case = models.CharField(max_length=500, blank=True, default="")
    status_message = models.CharField(max_length=200, blank=True, default="")
    forward_citation_count = models.IntegerField(null=True, blank=True)
    verify_status = models.CharField(
        max_length=20, choices=VERIFY_STATUS_CHOICES, default="none"
    )
    review_summary = models.TextField(blank=True, default="")
    has_negative_history = models.BooleanField(null=True, default=None)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"Result {self.position}: {self.case_name[:50]}"

    @property
    def unassessed_count(self):
        return self.verifications.filter(summary="").count()

    @property
    def is_ruled_out(self):
        return self.relevance in ("low", "rejected")


TREATMENT_CHOICES = [
    ("", ""),
    ("positive", "Positive"),
    ("negative", "Negative"),
    ("neutral", "Neutral"),
    ("distinguished", "Distinguished"),
]


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
    treatment = models.CharField(
        max_length=20, choices=TREATMENT_CHOICES, blank=True, default=""
    )
    summary = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"Verification {self.position}: {self.case_name[:50]}"


BRIEF_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("generating", "Generating"),
    ("complete", "Complete"),
    ("error", "Error"),
]


class CaseBrief(AuditMixin):
    matter = models.ForeignKey(
        "matters.Matter",
        on_delete=models.CASCADE,
        related_name="case_briefs",
    )
    result = models.ForeignKey(
        ResearchResult,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="case_briefs",
    )
    case_name = models.CharField(max_length=500, blank=True, default="")
    citation = models.CharField(max_length=300, blank=True, default="")
    court = models.CharField(max_length=200, blank=True, default="")
    date_filed = models.CharField(max_length=20, blank=True, default="")
    cluster_id = models.IntegerField(null=True, blank=True)
    query_text = models.TextField(blank=True, default="")
    brief = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=BRIEF_STATUS_CHOICES, default="pending"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Brief: {self.case_name[:50]}"
