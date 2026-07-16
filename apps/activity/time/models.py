from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.activity.models import ActivityCategory
from apps.invoicing.invoices.models import Invoice
from apps.matters.models import Matter
from utils.models import AuditMixin


class TimeEntry(AuditMixin, models.Model):
    date = models.DateField(null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    actions = models.TextField(null=True)
    hours = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    rate = models.IntegerField(null=True)
    comp = models.BooleanField(default=False)
    entered = models.BooleanField(default=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True
    )
    # One coding bucket per entry (accounting-style); null = uncategorized.
    category = models.ForeignKey(
        ActivityCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.actions}"

    class Meta:
        db_table = "app_activity"
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["matter"]),
        ]

    @property
    def fee(self):
        return self.hours * self.rate

    @property
    def locked(self):
        """On an invoice that has left DRAFT — no longer eligible for
        editing (matter/comp/amount changes). Labels stay applicable."""
        return self.invoice_id is not None and self.invoice.status != "DRAFT"

    @property
    def discounted_fee(self):
        if self.comp:
            return self.hours * self.rate
        else:
            return 0


class AbbreviationCode(AuditMixin, models.Model):
    code = models.CharField(max_length=50, unique=True)
    expansion = models.TextField()
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.code} → {self.expansion}"

    class Meta:
        db_table = "abbreviation_codes"
        ordering = ["code"]
