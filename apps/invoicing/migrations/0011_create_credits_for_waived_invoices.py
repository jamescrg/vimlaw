from decimal import Decimal

from django.db import migrations
from django.db.models import F, Sum


def calculate_invoice_total(TimeEntry, ExpenseEntry, invoice):
    """Calculate the final_total for an invoice (can't use model property in migration)."""
    # Sum of non-comp fees: hours * rate
    fees_result = (
        TimeEntry.objects.filter(invoice=invoice)
        .exclude(comp=True)
        .aggregate(total=Sum(F("hours") * F("rate")))
    )
    net_fees = fees_result["total"] or Decimal("0")

    # Sum of non-comp expenses
    expenses_result = (
        ExpenseEntry.objects.filter(invoice=invoice)
        .exclude(comp=True)
        .aggregate(total=Sum("amount"))
    )
    net_expenses = expenses_result["total"] or Decimal("0")

    # final_total = net_fees + net_expenses - discount
    return net_fees + net_expenses - (invoice.discount or Decimal("0"))


def create_credits_for_waived_invoices(apps, schema_editor):
    Invoice = apps.get_model("invoicing", "Invoice")
    Credit = apps.get_model("invoicing", "Credit")
    TimeEntry = apps.get_model("activity", "TimeEntry")
    ExpenseEntry = apps.get_model("activity", "ExpenseEntry")

    # Get all waived invoices
    waived_invoices = Invoice.objects.filter(status="WAIVED").order_by("date_issued")

    # Group by matter: collect totals, dates, and invoice IDs
    matter_data = {}
    for invoice in waived_invoices:
        if invoice.matter_id is None:
            continue

        invoice_total = calculate_invoice_total(TimeEntry, ExpenseEntry, invoice)

        if invoice.matter_id not in matter_data:
            matter_data[invoice.matter_id] = {
                "total": Decimal("0"),
                "date": invoice.date_issued,
                "invoice_ids": [],
            }

        matter_data[invoice.matter_id]["total"] += invoice_total
        matter_data[invoice.matter_id]["invoice_ids"].append(str(invoice.id))
        # Use the latest invoice date
        if invoice.date_issued > matter_data[invoice.matter_id]["date"]:
            matter_data[invoice.matter_id]["date"] = invoice.date_issued

    # Create credits for each matter
    for matter_id, data in matter_data.items():
        if data["total"] <= 0:
            continue

        # Format detail text with invoice numbers
        invoice_ids = data["invoice_ids"]
        if len(invoice_ids) == 1:
            detail = f"Waived: Invoice #{invoice_ids[0]}"
        else:
            detail = f"Waived: Invoices #{', #'.join(invoice_ids)}"

        Credit.objects.create(
            matter_id=matter_id,
            date=data["date"],
            amount=data["total"],
            detail=detail,
        )


def reverse_credits_for_waived_invoices(apps, schema_editor):
    Credit = apps.get_model("invoicing", "Credit")
    # Delete credits that start with "Waived: Invoice"
    Credit.objects.filter(detail__startswith="Waived: Invoice").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("invoicing", "0010_alter_invoice_status"),
        ("activity", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_credits_for_waived_invoices,
            reverse_credits_for_waived_invoices,
        ),
    ]
