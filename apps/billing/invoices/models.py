from django.db import models

from apps.accounts.models import CustomUser
from apps.matters.models import Matter

INVOICE_STATUS = (
    ("DRAFT", "Draft"),
    ("APPROVED", "Approved"),
    ("SENT", "Sent"),
    ("CANCELED", "Canceled"),
    ("PAID", "Paid"),
    ("WAIVED", "Waived"),
)


class Invoice(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(Matter, on_delete=models.SET_NULL, null=True, blank=True)
    date_limit = models.DateField()
    date_issued = models.DateField()
    message = models.TextField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    show_comp = models.BooleanField(default=False)
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default="DRAFT")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pdf_file = models.FileField(upload_to="invoices/", null=True, blank=True)

    def __str__(self):
        return f"Invoice #{self.id}"

    class Meta:
        indexes = [models.Index(fields=["matter"])]
        db_table = "app_billing_invoice"

    def save(self, *args, **kwargs):
        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.time.models import TimeEntry

        invoice = super().save(*args, **kwargs)

        TimeEntry.objects.filter(
            matter=self.matter,
            date__lte=self.date_limit,
            invoice__isnull=True,
            entered=0,
        ).update(invoice_id=self.id)

        ExpenseEntry.objects.filter(
            matter=self.matter,
            date__lte=self.date_limit,
            invoice__isnull=True,
            entered=0,
        ).update(invoice_id=self.id)

        return invoice

    @property
    def status_display(self):
        return dict(INVOICE_STATUS).get(self.status)

    @property
    def value(self):
        from apps.activity.time.models import TimeEntry

        time_entries = TimeEntry.objects.filter(invoice=self.id)
        gross_fees = sum(entry.fee for entry in time_entries)
        comp_fees = sum(entry.fee for entry in time_entries.filter(comp=1))
        net_fees = gross_fees - comp_fees

        from apps.activity.expenses.models import ExpenseEntry

        expense_entries = ExpenseEntry.objects.filter(invoice=self.id)
        gross_expenses = sum(entry.amount for entry in expense_entries)
        comp_expenses = sum(entry.amount for entry in expense_entries.filter(comp=1))
        net_expenses = gross_expenses - comp_expenses

        pre_discount_total = net_fees + net_expenses
        final_total = pre_discount_total - self.discount

        return {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "pre_discount_total": pre_discount_total,
            "final_total": final_total,
        }
