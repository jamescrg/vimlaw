from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.billing.invoice.models import Invoice


def calculate_inv_amount(invoice: Invoice):
    if invoice.show_comp:
        entries = TimeEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
    else:
        entries = TimeEntry.objects.filter(
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")

    # total fees prior to any comp hours
    entries_gross_total = (
        entries.annotate(
            fee=ExpressionWrapper(F("hours") * F("rate"), output_field=DecimalField())
        ).aggregate(total_fee=Sum("fee"))["total_fee"]
    ) or 0

    # total fees for comp hours
    entries_comp_total = (
        entries.filter(comp=1)
        .annotate(
            fee=ExpressionWrapper(F("hours") * F("rate"), output_field=DecimalField())
        )
        .aggregate(total_fee=Sum("fee"))["total_fee"]
    ) or 0

    # net fees after comp hours
    entries_net_total = entries_gross_total - entries_comp_total

    if invoice.show_comp:
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
    else:
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")

    expenses_gross_total = (
        expenses.aggregate(total_amount=Sum("amount"))["total_amount"] or 0
    )
    expenses_comp_total = (
        expenses.filter(comp=1).aggregate(total_amount=Sum("amount"))["total_amount"]
        or 0
    )
    expenses_net_total = expenses_gross_total - expenses_comp_total

    pre_discount_total = entries_net_total + expenses_net_total
    invoice_total = pre_discount_total - invoice.discount

    return {
        "entries": entries,
        "expenses": expenses,
        "entries_gross_total": entries_gross_total,
        "entries_comp_total": entries_comp_total,
        "entries_net_total": entries_net_total,
        "expenses_gross_total": expenses_gross_total,
        "expenses_comp_total": expenses_comp_total,
        "expenses_net_total": expenses_net_total,
        "invoice_total": invoice_total,
    }
