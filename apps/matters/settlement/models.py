from django.db import models
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin


class SettlementEntry(AuditMixin, models.Model):
    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    medium = models.CharField(max_length=50, blank=True, null=True)
    type = models.CharField(max_length=150, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    notes = models.CharField(max_length=50, blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.amount}"

    class Meta:
        db_table = "app_settlement"
