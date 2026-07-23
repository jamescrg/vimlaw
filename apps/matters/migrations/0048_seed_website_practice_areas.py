from django.db import migrations

# Practice areas the website's intake questionnaire can map onto; the
# rest of the form's dispute natures match rows that already exist
# (Boundary, Title, HOA, LLT-L, LLT-T, Construction, Collections, General)
WEBSITE_AREAS = ["Easement", "Purchase / Sale", "Fraud", "Commercial"]


def seed(apps, schema_editor):
    PracticeArea = apps.get_model("matters", "PracticeArea")
    for name in WEBSITE_AREAS:
        PracticeArea.objects.get_or_create(name=name)


def unseed(apps, schema_editor):
    PracticeArea = apps.get_model("matters", "PracticeArea")
    PracticeArea.objects.filter(name__in=WEBSITE_AREAS, intakes=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("matters", "0047_historicalmatter_report_reclaim_comp_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
