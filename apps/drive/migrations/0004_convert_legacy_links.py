"""Convert the old name-based Drive links into DriveFolderMapping rows.

Runs without Drive access (no API calls in migrations): rows get
folder_id=NULL and the cached path; the next full sync or Drive Folder
modal open resolves them to ids. Two sources:

- Proceeding.drive_folder (record-folder links) -> Record mapping.
- The retired "Key Documents" convention: every distinct Key Documents
  folder path that synced Evidence documents came through -> Evidence
  mapping (nested paths such as "Evidence/Key Documents" are kept so those
  folders keep syncing after deploy). Those documents are attached to the
  new row by drive_path prefix, the only time paths are used for that.
"""

from django.db import migrations

KEY_FOLDER = "Key Documents"


def forwards(apps, schema_editor):
    Proceeding = apps.get_model("matters", "Proceeding")
    Document = apps.get_model("case", "Document")
    Mapping = apps.get_model("drive", "DriveFolderMapping")

    for proceeding in Proceeding.objects.exclude(drive_folder__isnull=True).exclude(
        drive_folder=""
    ).select_related("matter"):
        matter = proceeding.matter
        if matter is None or not matter.drive_folder:
            continue
        mapping, _ = Mapping.objects.get_or_create(
            matter=matter,
            folder_id=None,
            folder_path=proceeding.drive_folder,
            defaults={"category": "Record", "proceeding": proceeding},
        )
        Document.objects.filter(
            matter=matter,
            drive_file_id__isnull=False,
            drive_path__startswith=f"{matter.drive_folder}/{proceeding.drive_folder}/",
        ).update(drive_mapping=mapping)

    synced = Document.objects.filter(
        drive_file_id__isnull=False, drive_mapping__isnull=True
    ).select_related("matter")
    for doc in synced:
        matter = doc.matter
        if matter is None or not matter.drive_folder or not doc.drive_path:
            continue
        parts = doc.drive_path.split("/")
        # parts[0] is the matter folder, parts[-1] the file name.
        inner = parts[1:-1]
        if KEY_FOLDER not in inner:
            continue
        path = "/".join(inner[: inner.index(KEY_FOLDER) + 1])
        mapping, _ = Mapping.objects.get_or_create(
            matter=matter,
            folder_id=None,
            folder_path=path,
            defaults={"category": "Evidence", "proceeding": None},
        )
        Document.objects.filter(pk=doc.pk).update(drive_mapping=mapping)


class Migration(migrations.Migration):
    dependencies = [
        ("drive", "0003_drivefoldermapping_drivematterstate"),
        ("case", "0082_document_drive_mapping"),
        ("matters", "0051_matter_drive_folder_id"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
