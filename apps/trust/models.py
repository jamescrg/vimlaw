from django.db import models
from simple_history.models import HistoricalRecords

from apps.contacts.models import Contact
from utils.models import AuditMixin


class Transaction(AuditMixin, models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    type = models.CharField(max_length=10, null=True)
    description = models.CharField(max_length=255, null=True)
    amount = models.DecimalField(max_digits=9, decimal_places=2, null=True)
    entered = models.BooleanField(default=False)
    confirmed = models.BooleanField(default=False)
    # Online-deposit provenance (blank for manually-entered transactions). Lets a
    # settlement/return webhook find this row to reconcile it.
    processor = models.CharField(max_length=20, blank=True, default="")
    processor_txn_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    processor_status = models.CharField(max_length=20, blank=True, default="")
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.description} : {self.id}"

    class Meta:
        db_table = "app_trust"
