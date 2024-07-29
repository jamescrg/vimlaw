from django.db import models

from apps.accounts.models import CustomUser
from apps.invoicing.models import Invoice
from apps.matters.models import Matter


class TimeEntry(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    actions = models.TextField(null=True)
    hours = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    rate = models.IntegerField(null=True)
    comp = models.IntegerField(blank=True, null=True)
    entered = models.IntegerField(blank=True, null=True)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"{self.actions}"

    class Meta:
        db_table = "app_activity"

    @property
    def fee(self):
        return self.hours * self.rate


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
