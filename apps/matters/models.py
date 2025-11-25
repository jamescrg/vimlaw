from django.db import models

from apps.contacts.models import Contact


class Matter(models.Model):
    user_id = models.IntegerField(null=True)
    name = models.CharField(max_length=50, null=True)
    work_status = models.CharField(max_length=255, null=True)
    description = models.CharField(max_length=255, null=True)
    status = models.CharField(max_length=50, null=True)
    date_start = models.DateField(null=True)
    date_end = models.DateField(blank=True, null=True)
    firm = models.CharField(max_length=50, null=True)
    clio_matter_id = models.CharField(max_length=500, null=True, blank=True)
    client_reference_id = models.CharField(max_length=50, blank=True, null=True)
    practice_area = models.CharField(max_length=50, null=True)
    contacts = models.ManyToManyField(Contact, through="Relationship")
    client = models.ForeignKey(
        Contact, related_name="client_matters", on_delete=models.SET_NULL, null=True
    )

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["client"]),
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

        super().save(*args, **kwargs)

    @property
    def value(self):
        from django.db.models import Case, DecimalField, F, Sum, Value, When

        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.time.models import TimeEntry
        from apps.invoicing.invoices.models import Invoice
        from apps.invoicing.payments.models import Payment

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
                        When(comp=1, then=F("hours") * F("rate")),
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
                        When(comp=1, then=F("amount")),
                        default=Value(0),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            )
            gross = result["gross_expenses"] or 0
            comp = result["comp_expenses"] or 0
            return gross, comp

        # Total fees and expenses (all entries for this matter)
        gross_fees, comp_fees = aggregate_fees(TimeEntry.objects.filter(matter=self))
        net_fees = gross_fees - comp_fees

        gross_expenses, comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(matter=self)
        )
        net_expenses = gross_expenses - comp_expenses

        total = {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "net_fees_and_expenses": net_fees + net_expenses,
        }

        # Unbilled fees and expenses (entered=0, no invoice)
        unbilled_gross_fees, unbilled_comp_fees = aggregate_fees(
            TimeEntry.objects.filter(matter=self, entered=0, invoice__isnull=True)
        )
        unbilled_net_fees = unbilled_gross_fees - unbilled_comp_fees

        unbilled_gross_expenses, unbilled_comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(matter=self, entered=0, invoice__isnull=True)
        )
        unbilled_net_expenses = unbilled_gross_expenses - unbilled_comp_expenses

        unbilled = {
            "gross_fees": unbilled_gross_fees,
            "comp_fees": unbilled_comp_fees,
            "net_fees": unbilled_net_fees,
            "gross_expenses": unbilled_gross_expenses,
            "comp_expenses": unbilled_comp_expenses,
            "net_expenses": unbilled_net_expenses,
            "net_fees_and_expenses": unbilled_net_fees + unbilled_net_expenses,
        }

        # Billed = total - unbilled
        billed = {key: total[key] - unbilled[key] for key in total.keys()}

        # Invoice totals - aggregate from time/expense entries on SENT/PAID invoices
        invoice_fees, invoice_comp_fees = aggregate_fees(
            TimeEntry.objects.filter(matter=self, invoice__status__in=["SENT", "PAID"])
        )
        invoice_expenses, invoice_comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(
                matter=self, invoice__status__in=["SENT", "PAID"]
            )
        )
        invoice_discount = (
            Invoice.objects.filter(matter=self, status__in=["SENT", "PAID"]).aggregate(
                total_discount=Sum("discount")
            )["total_discount"]
            or 0
        )

        billed_invoices = (
            (invoice_fees - invoice_comp_fees)
            + (invoice_expenses - invoice_comp_expenses)
            - invoice_discount
        )

        payment_sum = (
            Payment.objects.filter(matter=self).aggregate(models.Sum("amount"))[
                "amount__sum"
            ]
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


class Role(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter_role"


class Relationship(models.Model):
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
    )
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)

    class Meta:
        db_table = "app_matter_relationship"

    def __str__(self):
        return f"matter: {self.matter.id}, contact: {self.contact.id}, role: {self.role.id}"
