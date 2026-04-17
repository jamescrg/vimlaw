"""Migrate importance 1-3 to Normal (4) after expanding to 7-level scale."""

from django.db import migrations


def migrate_to_normal(apps, schema_editor):
    Note = apps.get_model("notes", "Note")
    Note.objects.filter(importance__lte=3).update(importance=4)


class Migration(migrations.Migration):

    dependencies = [
        ("notes", "0016_importance_7_levels"),
    ]

    operations = [
        migrations.RunPython(migrate_to_normal, migrations.RunPython.noop),
    ]
