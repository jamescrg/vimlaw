# The drafting remodel: companion-first, integrated into case AI chat.
# DraftSession/DraftVersion (server-side working copies, versions, publish)
# are removed; DraftLink pins a conversation to a Drive file instead. Old
# draft conversations belonged to the retired standalone window (matter-less,
# invisible in case chat), so they are deleted with their sessions. Version
# blobs are NOT deleted here (django_cleanup signals do not fire in
# migrations): clear the storage bucket's drafts/ prefix after deploying.

import django.db.models.deletion
from django.db import migrations, models


def purge_old_draft_data(apps, schema_editor):
    CompanionRound = apps.get_model("drafts", "CompanionRound")
    DraftSession = apps.get_model("drafts", "DraftSession")
    Conversation = apps.get_model("case", "Conversation")

    CompanionRound.objects.all().delete()
    conversation_ids = list(
        DraftSession.objects.exclude(conversation=None).values_list(
            "conversation_id", flat=True
        )
    )
    Conversation.objects.filter(id__in=conversation_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("case", "0073_conversation_kind_conversation_research_depth_and_more"),
        ("drafts", "0002_draftsession_companion_seen_and_more"),
    ]

    operations = [
        migrations.RunPython(purge_old_draft_data, migrations.RunPython.noop),
        migrations.CreateModel(
            name="DraftLink",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("drive_file_id", models.CharField(max_length=128)),
                ("name", models.CharField(max_length=255)),
                ("doc_text", models.TextField(blank=True)),
                ("doc_text_at", models.DateTimeField(blank=True, null=True)),
                ("companion_seen", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "conversation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="draft_link",
                        to="case.conversation",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.RemoveField(model_name="companionround", name="session"),
        migrations.AddField(
            model_name="companionround",
            name="link",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rounds",
                to="drafts.draftlink",
            ),
        ),
        migrations.DeleteModel(name="DraftVersion"),
        migrations.DeleteModel(name="DraftSession"),
    ]
