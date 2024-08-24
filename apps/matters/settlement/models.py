from django.db import models

from apps.matters.models import Matter


class SettlementEntry(models.Model):
    user_id = models.IntegerField()
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    medium = models.CharField(max_length=50, blank=True, null=True)
    type = models.CharField(max_length=150, null=True)
    amount = models.CharField(max_length=50, null=True)
    notes = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.amount}"

    class Meta:
        db_table = "app_settlement"
