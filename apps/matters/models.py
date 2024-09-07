from django.db import models

from apps.contacts.models import Contact


class Matter(models.Model):
    user_id = models.IntegerField(null=True)
    name = models.CharField(max_length=50, null=True)
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

    @property
    def value(self):
        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.time.models import TimeEntry

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

        value = {
            "total": total,
            "unbilled": unbilled,
            "billed": billed,
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
