# Schema half of the matter-only change (data cleanup in 0012): matter FK
# becomes required, the global-name uniqueness constraint goes away, and
# default ordering becomes position-first to match the drag-reorder UI.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matters", "0028_group_created_at_group_created_by_group_updated_at_and_more"),
        ("activity", "0012_activitylabel_matter_required"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="activitylabel",
            name="uniq_global_label_name",
        ),
        migrations.AlterModelOptions(
            name="activitylabel",
            options={"ordering": ["position", "name"]},
        ),
        migrations.AlterField(
            model_name="activitylabel",
            name="matter",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="activity_labels",
                to="matters.matter",
            ),
        ),
        migrations.AlterField(
            model_name="historicalactivitylabel",
            name="matter",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="matters.matter",
            ),
        ),
    ]
