from django.db import migrations

CATEGORIES = [
    ("analysis", "Analysis"),
    ("drafting", "Drafting"),
    ("guide", "Guide"),
    ("interview", "Interview"),
    ("issue", "Issue"),
    ("note", "Note"),
    ("research", "Research"),
]


def create_category_folders(apps, schema_editor):
    NoteFolder = apps.get_model("notes", "NoteFolder")
    Note = apps.get_model("notes", "Note")

    for key, name in CATEGORIES:
        folder, _ = NoteFolder.objects.get_or_create(
            name=name,
            parent=None,
            defaults={"depth": 0},
        )
        Note.objects.filter(category=key, matter__isnull=True, folder__isnull=True).update(
            folder=folder
        )


def reverse_category_folders(apps, schema_editor):
    NoteFolder = apps.get_model("notes", "NoteFolder")
    Note = apps.get_model("notes", "Note")

    names = [name for _, name in CATEGORIES]
    folders = NoteFolder.objects.filter(name__in=names, parent__isnull=True)
    Note.objects.filter(folder__in=folders).update(folder=None)
    folders.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notes", "0010_add_notefolder_hierarchy"),
    ]

    operations = [
        migrations.RunPython(create_category_folders, reverse_category_folders),
    ]
