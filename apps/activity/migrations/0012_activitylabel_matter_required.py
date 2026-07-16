# Activity labels become matter-only: delete global labels (matter NULL —
# one unused row in production). The schema change follows in 0013; it must
# be a separate migration because Postgres can't ALTER the table in the same
# transaction as the delete's pending FK trigger events.

from django.db import migrations


def delete_global_labels(apps, schema_editor):
    ActivityLabel = apps.get_model("activity", "ActivityLabel")
    ActivityLabel.objects.filter(matter__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0011_activitylabel_claimed_activitylabel_matter_and_more"),
    ]

    operations = [
        migrations.RunPython(delete_global_labels, migrations.RunPython.noop),
    ]
