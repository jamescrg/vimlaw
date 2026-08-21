"""Apply the Closed-matter integration teardown to Complete matters.

Matter.save() now treats "Complete" like "Closed" for mirrors: Drive and
Gmail links dropped, Drive folder mappings removed, proceedings marked
Concluded. Existing Complete matters predate that rule (their Drive
folders already live under "Matters - Closed"), so bring them in line.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Matter = apps.get_model("matters", "Matter")
    Proceeding = apps.get_model("matters", "Proceeding")
    DriveFolderMapping = apps.get_model("drive", "DriveFolderMapping")
    DriveMatterState = apps.get_model("drive", "DriveMatterState")

    complete = Matter.objects.filter(status="Complete")
    ids = list(complete.values_list("pk", flat=True))
    Proceeding.objects.filter(matter_id__in=ids).update(status="Concluded")
    DriveFolderMapping.objects.filter(matter_id__in=ids).delete()
    DriveMatterState.objects.filter(matter_id__in=ids).delete()
    complete.update(
        drive_folder=None,
        drive_folder_id=None,
        gmail_label_id=None,
        gmail_label_name=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("matters", "0052_remove_proceeding_drive_folder"),
        ("drive", "0004_convert_legacy_links"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
