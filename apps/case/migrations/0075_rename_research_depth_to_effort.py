# research_depth (quick/standard/deep) becomes research_effort
# (low/medium/high): same three budget tiers, clearer name.

from django.db import migrations, models

FORWARD = {"quick": "low", "standard": "medium", "deep": "high"}
BACKWARD = {v: k for k, v in FORWARD.items()}


def _remap(apps, mapping, default):
    for model_name in ("Conversation", "HistoricalConversation"):
        model = apps.get_model("case", model_name)
        for old, new in mapping.items():
            model.objects.filter(research_effort=old).update(research_effort=new)
        model.objects.exclude(research_effort__in=mapping.values()).update(
            research_effort=default
        )


def forward(apps, schema_editor):
    _remap(apps, FORWARD, "medium")


def backward(apps, schema_editor):
    _remap(apps, BACKWARD, "standard")


class Migration(migrations.Migration):
    dependencies = [
        ("case", "0074_alter_conversation_kind_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="conversation",
            old_name="research_depth",
            new_name="research_effort",
        ),
        migrations.RenameField(
            model_name="historicalconversation",
            old_name="research_depth",
            new_name="research_effort",
        ),
        migrations.AlterField(
            model_name="conversation",
            name="research_effort",
            field=models.CharField(
                choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
                default="medium",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="historicalconversation",
            name="research_effort",
            field=models.CharField(
                choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
                default="medium",
                max_length=10,
            ),
        ),
        migrations.RunPython(forward, backward),
    ]
