# Labels become Categories: one coding bucket per entry (accounting-style)
# instead of many labels. ActivityLabel is RENAMED (not dropped) so existing
# rows survive; each entry's labels collapse onto a single category FK
# (preferring the claimed label — the guard ensured at most one), then the
# label M2Ms go away. Flat fees lose their (never-surfaced) labels entirely.

import django.db.models.deletion
from django.db import migrations, models


def copy_labels_to_category(apps, schema_editor):
    TimeEntry = apps.get_model("activity", "TimeEntry")
    ExpenseEntry = apps.get_model("activity", "ExpenseEntry")

    for entry in TimeEntry.objects.filter(labels__isnull=False).distinct():
        labels = sorted(
            entry.labels.all(),
            key=lambda lab: (not lab.claimed, lab.position, lab.name),
        )
        entry.category_id = labels[0].id
        entry.save(update_fields=["category"])

    for expense in ExpenseEntry.objects.filter(labels__isnull=False).distinct():
        labels = sorted(expense.labels.all(), key=lambda lab: (lab.position, lab.name))
        expense.activity_category_id = labels[0].id
        expense.save(update_fields=["activity_category"])


class Migration(migrations.Migration):
    dependencies = [
        ("matters", "0043_backfill_client_relationships"),
        ("activity", "0013_activitylabel_matter_only_schema"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ActivityLabel",
            new_name="ActivityCategory",
        ),
        migrations.RenameModel(
            old_name="HistoricalActivityLabel",
            new_name="HistoricalActivityCategory",
        ),
        migrations.AlterModelTable(
            name="activitycategory",
            table="app_activity_category",
        ),
        migrations.AlterModelOptions(
            name="historicalactivitycategory",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical activity category",
                "verbose_name_plural": "historical activity categorys",
            },
        ),
        migrations.RemoveConstraint(
            model_name="activitycategory",
            name="uniq_label_name_per_matter",
        ),
        migrations.AddConstraint(
            model_name="activitycategory",
            constraint=models.UniqueConstraint(
                fields=("matter", "name"),
                name="uniq_category_name_per_matter",
                violation_error_message="This matter already has a category with this name.",
            ),
        ),
        migrations.AlterField(
            model_name="activitycategory",
            name="matter",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="activity_categories",
                to="matters.matter",
            ),
        ),
        migrations.AddField(
            model_name="timeentry",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="time_entries",
                to="activity.activitycategory",
            ),
        ),
        migrations.AddField(
            model_name="expenseentry",
            name="activity_category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="expense_entries",
                to="activity.activitycategory",
            ),
        ),
        migrations.AddField(
            model_name="historicaltimeentry",
            name="category",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="activity.activitycategory",
            ),
        ),
        migrations.AddField(
            model_name="historicalexpenseentry",
            name="activity_category",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="activity.activitycategory",
            ),
        ),
        migrations.RunPython(copy_labels_to_category, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="timeentry",
            name="labels",
        ),
        migrations.RemoveField(
            model_name="expenseentry",
            name="labels",
        ),
        migrations.RemoveField(
            model_name="flatfeeentry",
            name="labels",
        ),
    ]
