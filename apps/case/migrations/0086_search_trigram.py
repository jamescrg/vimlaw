# pg_trgm powers the agent search's typo-tolerant fallback: when no
# full-text variant matches, near-miss titles and descriptions are found
# by word similarity. The GIN indexes keep that fallback fast over the
# watson index table.

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("case", "0085_sonnet5_picker_order"),
        ("watson", "0001_initial"),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS watson_searchentry_title_trgm "
                "ON watson_searchentry USING gin (title gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS watson_searchentry_title_trgm;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS watson_searchentry_description_trgm "
                "ON watson_searchentry USING gin (description gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS watson_searchentry_description_trgm;",
        ),
    ]
