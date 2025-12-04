from django.db import migrations


def update_waived_to_uncollectible(apps, schema_editor):
    Invoice = apps.get_model("invoicing", "Invoice")
    Invoice.objects.filter(status="WAIVED").update(status="UNCOLLECTIBLE")


def reverse_uncollectible_to_waived(apps, schema_editor):
    Invoice = apps.get_model("invoicing", "Invoice")
    Invoice.objects.filter(status="UNCOLLECTIBLE").update(status="WAIVED")


class Migration(migrations.Migration):

    dependencies = [
        ("invoicing", "0011_create_credits_for_waived_invoices"),
    ]

    operations = [
        migrations.RunPython(
            update_waived_to_uncollectible,
            reverse_uncollectible_to_waived,
        ),
    ]
