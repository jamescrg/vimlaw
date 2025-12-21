from django.db import models
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin


class Credit(AuditMixin, models.Model):
    matter = models.ForeignKey(Matter, on_delete=models.PROTECT)
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    detail = models.CharField(max_length=255, null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Credit #{self.id} - {self.matter}"

    class Meta:
        indexes = [models.Index(fields=["matter"])]
        db_table = "app_invoicing_credit"

    @property
    def amount_unapplied(self):
        """Calculate the amount of this credit not yet applied to invoices."""
        applied = (
            self.applications.aggregate(models.Sum("amount_applied"))[
                "amount_applied__sum"
            ]
            or 0
        )
        return self.amount - applied
