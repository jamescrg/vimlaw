from django.db import models
from apps.contacts.models import Contact


class Transaction(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    type = models.CharField(max_length=10, null=True)
    description = models.CharField(max_length=255, null=True)
    amount = models.DecimalField(max_digits=9, decimal_places=2, null=True)
    entered = models.IntegerField(blank=True, null=True)
    confirmed = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.description} : {self.id}"

    class Meta:
        db_table = "app_trust"
