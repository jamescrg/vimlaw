# Seed the starter relationship types. get_or_create by label so re-running
# (or a pre-existing user-created type with the same label) is harmless.

from django.db import migrations

SEED_TYPES = [
    ("Spouse of", ""),
    ("Parent of", "Child of"),
    ("Sibling of", ""),
    ("Assistant to", "Assisted by"),
    ("Emergency contact for", "Has emergency contact"),
    ("Employer of", "Employee of"),
    ("Colleague of", ""),
    ("Staff attorney for", "Has staff attorney"),
    ("Referred", "Referred by"),
    ("Power of attorney for", "Has power of attorney"),
]


def seed(apps, schema_editor):
    RelationshipType = apps.get_model("contacts", "RelationshipType")
    for label, inverse in SEED_TYPES:
        RelationshipType.objects.get_or_create(
            label=label, defaults={"inverse_label": inverse}
        )


def unseed(apps, schema_editor):
    RelationshipType = apps.get_model("contacts", "RelationshipType")
    RelationshipType.objects.filter(
        label__in=[label for label, _ in SEED_TYPES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0008_relationshiptype_historicalcontactrelationship_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
