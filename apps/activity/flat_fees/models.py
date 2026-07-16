from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.invoicing.invoices.models import Invoice
from apps.matters.models import Matter
from utils.models import AuditMixin


class FlatFeeEntry(AuditMixin, models.Model):
    date = models.DateField(null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    description = models.TextField(null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comp = models.BooleanField(default=False)
    entered = models.BooleanField(default=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_flat_fees"
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["matter"]),
        ]

    @property
    def discounted_amount(self):
        if self.comp:
            return self.amount
        else:
            return 0
