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
        elif self.status == "Open":
            # Mark client as current if the matter was reopened
            if self.client and self.client.client_status == "Former":
                Contact.objects.filter(pk=self.client.pk).update(
                    client_status="Current"
                )

        super().save(*args, **kwargs)

    @property
    def value(self):
        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.time.models import TimeEntry
        from apps.invoicing.invoices.models import Invoice
        from apps.invoicing.payments.models import Payment

        # total fees
        time_entries = TimeEntry.objects.filter(matter=self)
        gross_fees = sum(entry.fee for entry in time_entries)
        comp_fees = sum(entry.fee for entry in time_entries.filter(comp=1))
        net_fees = gross_fees - comp_fees

        # total expenses
        expenses = ExpenseEntry.objects.filter(matter=self)
        gross_expenses = sum(expense.amount for expense in expenses)
        comp_expenses = sum(expense.amount for expense in expenses.filter(comp=1))
        net_expenses = gross_expenses - comp_expenses
        net_fees_and_expenses = net_fees + net_expenses

        total = {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "net_fees_and_expenses": net_fees_and_expenses,
        }

        # unbilled fees
        time_entries = time_entries.filter(matter=self, entered=0, invoice__isnull=True)
        gross_fees = sum(entry.fee for entry in time_entries)
        comp_fees = sum(entry.fee for entry in time_entries.filter(comp=1))
        net_fees = gross_fees - comp_fees

        # unbilled expenses
        expenses = expenses.filter(matter=self, entered=0, invoice__isnull=True)
        gross_expenses = sum(expense.amount for expense in expenses)
        comp_expenses = sum(expense.amount for expense in expenses.filter(comp=1))
        net_expenses = gross_expenses - comp_expenses
        net_fees_and_expenses = net_fees + net_expenses

        unbilled = {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "net_fees_and_expenses": net_fees_and_expenses,
        }

        billed = {}
        for key in total.keys():
            billed[key] = total[key] - unbilled[key]

        invoices = Invoice.objects.filter(matter=self, status__in=["SENT", "PAID"])
        billed_invoices = sum(invoice.value["final_total"] for invoice in invoices)

        payment_sum = (
            Payment.objects.filter(matter=self).aggregate(models.Sum("amount"))[
                "amount__sum"
            ]
            or 0
        )

        invoice_due = billed_invoices - payment_sum

        invoices = {
            "billed": billed_invoices,
            "payment_sum": payment_sum,
            "due": invoice_due,
        }

        value = {
            "total": total,
            "unbilled": unbilled,
            "billed": billed,
            "invoices": invoices,
        }

        return value


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
