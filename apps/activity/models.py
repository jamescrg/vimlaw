from django.db import models
from simple_history.models import HistoricalRecords

from utils.models import AuditMixin

COLOR_CHOICES = [
    ("blue", "Blue"),
    ("gray", "Gray"),
    ("green", "Green"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("red", "Red"),
    ("yellow", "Yellow"),
]


class ActivityCategory(AuditMixin, models.Model):
    """A matter's coding buckets for activity — like accounting transaction
    codes, each entry lives in exactly one category (or none).

    Claimed categories become the sections of the matter's Fee Claim Report,
    ordered by position. Position is set by drag-reordering on the
    Categories tab, never edited directly.
    """

    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default="gray")
    matter = models.ForeignKey(
        "matters.Matter",
        on_delete=models.CASCADE,
        related_name="activity_categories",
    )
    claimed = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_activity_category"
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["matter", "name"],
                name="uniq_category_name_per_matter",
                violation_error_message="This matter already has a category with this name.",
            ),
        ]
