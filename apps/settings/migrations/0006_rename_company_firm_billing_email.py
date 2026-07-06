from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings", "0005_remove_company_payment_background_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Company",
            new_name="Firm",
        ),
        migrations.AlterModelOptions(
            name="firm",
            options={"verbose_name_plural": "firms"},
        ),
        migrations.AddField(
            model_name="firm",
            name="billing_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
