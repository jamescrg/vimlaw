from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.invoicing.invoices.models import Invoice
from apps.matters.models import Matter
from utils.models import AuditMixin


class TimeEntry(AuditMixin, models.Model):
    date = models.DateField(null=True)
    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    actions = models.TextField(null=True)
    hours = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    rate = models.IntegerField(null=True)
    comp = models.BooleanField(default=False)
    entered = models.BooleanField(default=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True
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
