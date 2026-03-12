from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.activity.models import ActivityLabel
from apps.invoicing.invoices.models import Invoice
from apps.matters.models import Matter
from utils.models import AuditMixin


class ExpenseEntry(AuditMixin, models.Model):
    date = models.DateField(null=True)
    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(null=True)
    amount = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    comp = models.BooleanField(default=False)
    entered = models.BooleanField(default=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True
    )
    labels = models.ManyToManyField(
        ActivityLabel, related_name="expense_entries", blank=True
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_expenses"
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["matter"]),
        ]

    @property
    def slug(self):
        if self.category:
            return f"{self.category} - {self.description}"
        else:
            return self.description

    @property
    def discounted_amount(self):
        if self.comp:
            return self.amount
        else:
            return 0
