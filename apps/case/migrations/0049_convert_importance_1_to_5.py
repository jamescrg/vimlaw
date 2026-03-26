from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


def convert_importance(apps, schema_editor):
    """Invert and compress importance from 1-10 scale to 1-5 scale.

    Old: 1 (highest) to 10 (lowest)
    New: 1 (lowest) to 5 (highest)

    Mapping: 1-2→5, 3-4→4, 5-6→3, 7-8→2, 9-10→1
    """
    mapping = {1: 5, 2: 5, 3: 4, 4: 4, 5: 3, 6: 3, 7: 2, 8: 2, 9: 1, 10: 1}
    for model_name in ("Document", "Highlight", "Fact", "Witness", "CaseLaw"):
        Model = apps.get_model("case", model_name)
        for old_val, new_val in mapping.items():
            Model.objects.filter(importance=old_val).update(importance=new_val)


def reverse_importance(apps, schema_editor):
    """Reverse: expand importance from 1-5 back to 1-10 (using midpoint)."""
    mapping = {5: 1, 4: 3, 3: 5, 2: 7, 1: 9}
    for model_name in ("Document", "Highlight", "Fact", "Witness", "CaseLaw"):
        Model = apps.get_model("case", model_name)
        for old_val, new_val in mapping.items():
            Model.objects.filter(importance=old_val).update(importance=new_val)


class Migration(migrations.Migration):

    dependencies = [
        ("case", "0048_drop_old_research_tables"),
    ]

    operations = [
        migrations.RunPython(convert_importance, reverse_importance),
        migrations.AlterField(
            model_name="document",
            name="importance",
            field=models.PositiveIntegerField(
                default=3,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
        migrations.AlterField(
            model_name="highlight",
            name="importance",
            field=models.PositiveIntegerField(
                default=3,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
        migrations.AlterField(
            model_name="fact",
            name="importance",
            field=models.PositiveIntegerField(
                default=3,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
        migrations.AlterField(
            model_name="witness",
            name="importance",
            field=models.PositiveIntegerField(
                default=3,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
        migrations.AlterField(
            model_name="caselaw",
            name="importance",
            field=models.IntegerField(default=3),
        ),
    ]
