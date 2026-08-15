# research_effort becomes plain effort: Analysis mode now has effort
# levels too (context-assembly apparatus), so the field is mode-agnostic.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("case", "0075_rename_research_depth_to_effort"),
    ]

    operations = [
        migrations.RenameField(
            model_name="conversation",
            old_name="research_effort",
            new_name="effort",
        ),
        migrations.RenameField(
            model_name="historicalconversation",
            old_name="research_effort",
            new_name="effort",
        ),
    ]
