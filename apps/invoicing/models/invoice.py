from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from apps.accounts.models import CustomUser
from apps.matters.models import Matter

INVOICE_STATUS = (
    ("DRAFT", "Draft"),
    ("SENT", "Sent"),
    ("CANCELLED", "Cancelled"),
    ("APPROVED", "Approved"),
)


class Invoice(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(Matter, on_delete=models.SET_NULL, null=True, blank=True)
    date_from = models.DateField()
    date_to = models.DateField()
    date_issued = models.DateField()
    message = models.TextField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    show_comp = models.BooleanField(default=False)
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default="DRAFT")
    date_approved = models.DateTimeField(null=True, blank=True)
    date_sent = models.DateTimeField(null=True, blank=True)
    date_canceled = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Invoice #{self.id}"

    class Meta:
        indexes = [models.Index(fields=["matter"])]

    def save(self, *args, **kwargs):
        from apps.activity.models import ExpenseEntry, TimeEntry

        invoice = super().save(*args, **kwargs)

        TimeEntry.objects.filter(
            matter=self.matter,
            date__range=[self.date_from, self.date_to],
            invoice__isnull=True,
        ).update(invoice_id=self.id)

        ExpenseEntry.objects.filter(
            matter=self.matter,
            date__range=[self.date_from, self.date_to],
            invoice__isnull=True,
        ).update(invoice_id=self.id)

        return invoice

    @property
    def status_display(self):
        return dict(INVOICE_STATUS).get(self.status)

    @property
    def amount(self):
        from apps.activity.models import ExpenseEntry, TimeEntry

        time_entry_amount = (
            TimeEntry.objects.filter(invoice=self.id)
            .annotate(
                fee=ExpressionWrapper(
                    F("hours") * F("firm_rate"), output_field=DecimalField()
                )
            )
            .aggregate(total_fee=Sum("fee"))["total_fee"]
        ) or 0

        expense_amount = (
            ExpenseEntry.objects.filter(invoice=self.id).aggregate(
                total_amount=Sum("amount")
            )["total_amount"]
            or 0
        )

        return (time_entry_amount + expense_amount) - self.discount
