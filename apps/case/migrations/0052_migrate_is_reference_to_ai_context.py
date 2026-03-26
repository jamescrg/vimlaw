from django.db import migrations


def migrate_is_reference(apps, schema_editor):
    """Convert is_reference boolean to ai_context CharField."""
    Conversation = apps.get_model("case", "Conversation")
    Conversation.objects.filter(is_reference=True).update(ai_context="always")


def reverse_migration(apps, schema_editor):
    """Reverse: convert ai_context back to is_reference."""
    Conversation = apps.get_model("case", "Conversation")
    Conversation.objects.filter(ai_context="always").update(is_reference=True)
    Conversation.objects.filter(ai_context__in=["auto", "never"]).update(
        is_reference=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("case", "0051_add_conversation_ai_context_and_summary"),
    ]

    operations = [
        migrations.RunPython(migrate_is_reference, reverse_migration),
    ]
