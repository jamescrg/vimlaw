from django.db import models

from apps.matters.models import Matter


class Credit(models.Model):
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE)
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    detail = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Credit #{self.id} - {self.matter}"

    class Meta:
        indexes = [models.Index(fields=["matter"])]
        db_table = "app_invoicing_credit"

    @property
    def amount_unallocated(self):
        """Calculate the amount of this credit not yet allocated to invoices."""
        allocated = (
            self.applications.aggregate(models.Sum("amount_applied"))[
                "amount_applied__sum"
            ]
            or 0
        )
        return self.amount - allocated
