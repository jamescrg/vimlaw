from django.db import models

from apps.accounts.models import CustomUser
from apps.invoicing.invoices.models import Invoice
from apps.matters.models import Matter


class TimeEntry(models.Model):
    date = models.DateField(null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
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


class AbbreviationCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    expansion = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} → {self.expansion}"

    class Meta:
        db_table = "abbreviation_codes"
        ordering = ["code"]
