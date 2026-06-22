from django.db import models
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin


def invoice_upload_path(instance, filename):
    return f"invoices/{instance.matter_id}/{instance.pk}.pdf"


INVOICE_STATUS = (
    ("DRAFT", "Draft"),
    ("APPROVED", "Approved"),
    ("SENT", "Sent"),
    ("DEFERRED", "Deferred"),
    ("PAID", "Paid"),
    ("UNCOLLECTIBLE", "Uncollectible"),
    ("VOID", "Void"),
)


class Invoice(AuditMixin, models.Model):
    matter = models.ForeignKey(Matter, on_delete=models.SET_NULL, null=True, blank=True)
    date_limit = models.DateField()
    date_issued = models.DateField()
    message = models.TextField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    show_comp = models.BooleanField(default=True)
    discount = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default="DRAFT")
    pdf_file = models.FileField(upload_to=invoice_upload_path, null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Invoice #{self.id}"

    class Meta:
        indexes = [models.Index(fields=["matter"])]
        db_table = "app_invoicing_invoice"

    def save(self, *args, **kwargs):
        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.flat_fees.models import FlatFeeEntry
        from apps.activity.time.models import TimeEntry

        invoice = super().save(*args, **kwargs)

        if self.status == "DRAFT":
            TimeEntry.objects.filter(
                matter=self.matter,
                date__lte=self.date_limit,
                invoice__isnull=True,
                entered=False,
            ).update(invoice_id=self.id)

            ExpenseEntry.objects.filter(
                matter=self.matter,
                date__lte=self.date_limit,
                invoice__isnull=True,
                entered=False,
            ).update(invoice_id=self.id)

            FlatFeeEntry.objects.filter(
                matter=self.matter,
                date__lte=self.date_limit,
                invoice__isnull=True,
                entered=False,
            ).update(invoice_id=self.id)

        return invoice

    def void(self):
        """Void this invoice: release entries, remove applications, set status."""
        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.flat_fees.models import FlatFeeEntry
        from apps.activity.time.models import TimeEntry

        TimeEntry.objects.filter(invoice=self).update(invoice=None)
        ExpenseEntry.objects.filter(invoice=self).update(invoice=None)
        FlatFeeEntry.objects.filter(invoice=self).update(invoice=None)

        self.applications.all().delete()
        self.credit_applications.all().delete()

        Invoice.objects.filter(pk=self.pk).update(status="VOID")
        self.status = "VOID"

    @property
    def status_display(self):
        return dict(INVOICE_STATUS).get(self.status)

    @property
    def amount_remaining(self):
        """
        Calculate the amount still owed on this invoice after allocations.

        Hybrid approach for backward compatibility:
        - If status is "VOID" or "UNCOLLECTIBLE", return 0 (cancelled / written off
          as bad debt — nothing collectible)
        - If status is "PAID" and no allocations exist, return 0 (legacy invoices)
        - Otherwise, calculate based on allocations (new allocation system)
        """
        if self.status in ("VOID", "UNCOLLECTIBLE"):
            return 0

        total = self.value["final_total"]
        payment_allocated = (
            self.applications.aggregate(models.Sum("amount_applied"))[
                "amount_applied__sum"
            ]
            or 0
        )
        credit_allocated = (
            self.credit_applications.aggregate(models.Sum("amount_applied"))[
                "amount_applied__sum"
            ]
            or 0
        )

        # Legacy support: PAID invoices without allocations are considered fully paid
        if self.status == "PAID" and payment_allocated == 0 and credit_allocated == 0:
            return 0

        return total - payment_allocated - credit_allocated

    @property
    def value(self):
        from django.db.models import Case, DecimalField, F, Sum, Value, When

        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.flat_fees.models import FlatFeeEntry
        from apps.activity.time.models import TimeEntry

        # Aggregate fees using database-level calculation
        fee_result = TimeEntry.objects.filter(invoice=self.id).aggregate(
            gross_fees=Sum(
                F("hours") * F("rate"),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            ),
            comp_fees=Sum(
                Case(
                    When(comp=True, then=F("hours") * F("rate")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
        )
        gross_fees = fee_result["gross_fees"] or 0
        comp_fees = fee_result["comp_fees"] or 0
        net_fees = gross_fees - comp_fees

        # Aggregate expenses using database-level calculation
        expense_result = ExpenseEntry.objects.filter(invoice=self.id).aggregate(
            gross_expenses=Sum("amount"),
            comp_expenses=Sum(
                Case(
                    When(comp=True, then=F("amount")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
        )
        gross_expenses = expense_result["gross_expenses"] or 0
        comp_expenses = expense_result["comp_expenses"] or 0
        net_expenses = gross_expenses - comp_expenses

        # Aggregate flat fees using database-level calculation
        flat_fee_result = FlatFeeEntry.objects.filter(invoice=self.id).aggregate(
            gross_flat_fees=Sum("amount"),
            comp_flat_fees=Sum(
                Case(
                    When(comp=True, then=F("amount")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
        )
        gross_flat_fees = flat_fee_result["gross_flat_fees"] or 0
        comp_flat_fees = flat_fee_result["comp_flat_fees"] or 0
        net_flat_fees = gross_flat_fees - comp_flat_fees

        pre_discount_total = net_fees + net_expenses + net_flat_fees
        final_total = pre_discount_total - self.discount

        return {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "gross_flat_fees": gross_flat_fees,
            "comp_flat_fees": comp_flat_fees,
            "net_flat_fees": net_flat_fees,
            "pre_discount_total": pre_discount_total,
            "final_total": final_total,
        }
