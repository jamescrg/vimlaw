from django.db import models

from apps.matters.models import Matter

PAYMENT_METHOD_CHOICES = (("CHECK", "Check"), ("CARD", "Card"), ("TRUST", "Trust"))


class Payment(models.Model):
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE)
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
    detail = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Payment #{self.id} - {self.matter}"

    class Meta:
        indexes = [models.Index(fields=["matter"])]
        ordering = ["-date"]
        db_table = "app_invoicing_payment"

    @property
    def method_display(self):
        return dict(PAYMENT_METHOD_CHOICES).get(self.payment_method)

    @property
    def amount_unallocated(self):
        """Calculate the amount of this payment not yet allocated to invoices."""
        allocated = (
            self.applications.aggregate(models.Sum("amount_applied"))[
                "amount_applied__sum"
            ]
            or 0
        )
        return self.amount - allocated
