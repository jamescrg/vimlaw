from django.db import models
from simple_history.models import HistoricalRecords

from apps.contacts.models import Contact
from utils.models import AuditMixin

BILLING_TYPE_CHOICES = (
    ("HOURLY", "Hourly"),
    ("FLAT_FEE", "Flat Fee"),
)


class Matter(AuditMixin, models.Model):
    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    name = models.CharField(max_length=50, null=True)
    work_status = models.CharField(max_length=255, null=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=50, null=True)
    date_start = models.DateField(null=True)
    date_end = models.DateField(blank=True, null=True)

    clio_matter_id = models.CharField(max_length=500, null=True, blank=True)
    client_reference_id = models.CharField(max_length=50, blank=True, null=True)
    # Name of this matter's Google Drive folder under DRIVE_NOTES_ROOT, used to
    # attach synced case notes. Set via the link_drive_folders command.
    drive_folder = models.CharField(max_length=255, null=True, blank=True)
    practice_area = models.ForeignKey(
        "PracticeArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matters",
    )
    contacts = models.ManyToManyField(Contact, through="Relationship")
    client = models.ForeignKey(
        Contact, related_name="client_matters", on_delete=models.SET_NULL, null=True
    )
    jurisdiction = models.CharField(max_length=100, blank=True)
    billable = models.BooleanField(default=True)
    billing_type = models.CharField(
        max_length=20, choices=BILLING_TYPE_CHOICES, default="HOURLY"
    )
    flat_fee_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # Deferred-fee arrangement (e.g. hybrid agreements): fees accrue but are not
    # currently collectible, and the retainer is waived. Drives the low-clearance
    # exclusion regardless of whether the matter has been invoiced yet.
    deferred_fees = models.BooleanField(default=False)
    members = models.ManyToManyField(
        "accounts.CustomUser",
        related_name="assigned_matters",
        blank=True,
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["client"]),
            models.Index(fields=["billable"]),
            models.Index(fields=["billing_type"]),
        ]

    def save(self, *args, **kwargs):
        if self.status == "Closed":
            from apps.matters.proceedings.models import Proceeding

            # Mark all proceedings as concluded when matter is closed
            Proceeding.objects.filter(matter=self).update(status="Concluded")

            # Mark client as former if client has no open matters
            if (
                not Matter.objects.filter(client=self.client, status="Open")
                .exclude(pk=self.pk)
                .exists()
            ):
                Contact.objects.filter(pk=self.client.pk).update(client_status="Former")
        elif self.status == "Pending":
            # Mark client as pending if they have no open/complete matters
            if self.client and (
                not Matter.objects.filter(
                    client=self.client, status__in=["Open", "Complete"]
                )
                .exclude(pk=self.pk)
                .exists()
            ):
                Contact.objects.filter(pk=self.client.pk).update(
                    client_status="Pending"
                )
        elif self.status == "Open":
            # Mark client as current if the matter was reopened
            if self.client and self.client.client_status in ["Former", "Pending"]:
                Contact.objects.filter(pk=self.client.pk).update(
                    client_status="Current"
                )

        # Document files are stored by matter ID (see case.models
        # document_upload_path: documents/{matter_id}/{document_id}.ext), so a
        # name change never requires moving files. (Older builds embedded the
        # matter name in the path and rewrote every document on rename — slow,
        # and it reverted files to the deprecated name-based layout.)
        super().save(*args, **kwargs)

    @property
    def primary_proceeding(self):
        """Return the primary proceeding for this matter, if any."""
        from apps.matters.proceedings.models import Proceeding

        return Proceeding.objects.filter(matter=self, primary=True).first()

    @property
    def value(self):
        from django.db.models import Case, DecimalField, F, Sum, Value, When

        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.flat_fees.models import FlatFeeEntry
        from apps.activity.time.models import TimeEntry
        from apps.invoicing.applications.models import PaymentApplication
        from apps.invoicing.invoices.models import Invoice

        # Helper to build fee/expense aggregation dict
        def aggregate_fees(queryset):
            """Aggregate time entry fees using database-level calculation."""
            result = queryset.aggregate(
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
            gross = result["gross_fees"] or 0
            comp = result["comp_fees"] or 0
            return gross, comp

        def aggregate_expenses(queryset):
            """Aggregate expense amounts using database-level calculation."""
            result = queryset.aggregate(
                gross_expenses=Sum("amount"),
                comp_expenses=Sum(
                    Case(
                        When(comp=True, then=F("amount")),
                        default=Value(0),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            )
            gross = result["gross_expenses"] or 0
            comp = result["comp_expenses"] or 0
            return gross, comp

        def aggregate_flat_fees(queryset):
            """Aggregate flat-fee amounts using database-level calculation."""
            result = queryset.aggregate(
                gross_flat_fees=Sum("amount"),
                comp_flat_fees=Sum(
                    Case(
                        When(comp=True, then=F("amount")),
                        default=Value(0),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            )
            gross = result["gross_flat_fees"] or 0
            comp = result["comp_flat_fees"] or 0
            return gross, comp

        # Total fees and expenses (all entries for this matter)
        gross_fees, comp_fees = aggregate_fees(TimeEntry.objects.filter(matter=self))
        net_fees = gross_fees - comp_fees

        gross_expenses, comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(matter=self)
        )
        net_expenses = gross_expenses - comp_expenses

        gross_flat_fees, comp_flat_fees = aggregate_flat_fees(
            FlatFeeEntry.objects.filter(matter=self)
        )
        net_flat_fees = gross_flat_fees - comp_flat_fees

        total = {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "gross_flat_fees": gross_flat_fees,
            "comp_flat_fees": comp_flat_fees,
            "net_flat_fees": net_flat_fees,
            "net_fees_and_expenses": net_fees + net_expenses + net_flat_fees,
        }

        # Unbilled fees and expenses (entered=False, no invoice)
        unbilled_gross_fees, unbilled_comp_fees = aggregate_fees(
            TimeEntry.objects.filter(matter=self, entered=False, invoice__isnull=True)
        )
        unbilled_net_fees = unbilled_gross_fees - unbilled_comp_fees

        unbilled_gross_expenses, unbilled_comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(
                matter=self, entered=False, invoice__isnull=True
            )
        )
        unbilled_net_expenses = unbilled_gross_expenses - unbilled_comp_expenses

        unbilled_gross_flat_fees, unbilled_comp_flat_fees = aggregate_flat_fees(
            FlatFeeEntry.objects.filter(
                matter=self, entered=False, invoice__isnull=True
            )
        )
        unbilled_net_flat_fees = unbilled_gross_flat_fees - unbilled_comp_flat_fees

        unbilled = {
            "gross_fees": unbilled_gross_fees,
            "comp_fees": unbilled_comp_fees,
            "net_fees": unbilled_net_fees,
            "gross_expenses": unbilled_gross_expenses,
            "comp_expenses": unbilled_comp_expenses,
            "net_expenses": unbilled_net_expenses,
            "gross_flat_fees": unbilled_gross_flat_fees,
            "comp_flat_fees": unbilled_comp_flat_fees,
            "net_flat_fees": unbilled_net_flat_fees,
            "net_fees_and_expenses": (
                unbilled_net_fees + unbilled_net_expenses + unbilled_net_flat_fees
            ),
        }

        # Billed = total - unbilled
        billed = {key: total[key] - unbilled[key] for key in total.keys()}

        # Invoice totals - aggregate from time/expense/flat-fee entries on all invoices except DRAFT/APPROVED
        invoice_fees, invoice_comp_fees = aggregate_fees(
            TimeEntry.objects.filter(matter=self, invoice__isnull=False).exclude(
                invoice__status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"]
            )
        )
        invoice_expenses, invoice_comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(matter=self, invoice__isnull=False).exclude(
                invoice__status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"]
            )
        )
        invoice_flat_fees, invoice_comp_flat_fees = aggregate_flat_fees(
            FlatFeeEntry.objects.filter(matter=self, invoice__isnull=False).exclude(
                invoice__status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"]
            )
        )
        invoice_discount = (
            Invoice.objects.filter(matter=self)
            .exclude(status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"])
            .aggregate(total_discount=Sum("discount"))["total_discount"]
            or 0
        )

        billed_invoices = (
            (invoice_fees - invoice_comp_fees)
            + (invoice_expenses - invoice_comp_expenses)
            + (invoice_flat_fees - invoice_comp_flat_fees)
            - invoice_discount
        )

        # Payments are client-scoped; the amount paid toward THIS matter is the
        # sum of PaymentApplications to the matter's invoices (applied funds only).
        payment_sum = (
            PaymentApplication.objects.filter(invoice__matter=self).aggregate(
                models.Sum("amount_applied")
            )["amount_applied__sum"]
            or 0
        )

        invoices = {
            "billed": billed_invoices,
            "payment_sum": payment_sum,
            "due": billed_invoices - payment_sum,
        }

        return {
            "total": total,
            "unbilled": unbilled,
            "billed": billed,
            "invoices": invoices,
        }


class PracticeArea(AuditMixin, models.Model):
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_practice_area"
        ordering = ["name"]


class Group(AuditMixin, models.Model):
    name = models.CharField(max_length=50)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_matter_group"
        ordering = ["order"]


class Role(AuditMixin, models.Model):
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter_role"


class Relationship(AuditMixin, models.Model):
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
    )
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    history = HistoricalRecords()

    class Meta:
        db_table = "app_matter_relationship"

    def __str__(self):
        return f"matter: {self.matter.id}, contact: {self.contact.id}, role: {self.role.id}"
