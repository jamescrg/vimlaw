from django.db import models

from apps.accounts.models import CustomUser
from apps.billing.invoice.models import Invoice
from apps.matters.models import Matter


class ExpenseEntry(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    description = models.TextField(null=True)
    amount = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    comp = models.IntegerField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    entered = models.IntegerField(blank=True, null=True)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_expenses"
