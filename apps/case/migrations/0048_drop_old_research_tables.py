"""Drop the old standalone research app tables and migration records."""

from django.db import migrations


def drop_old_research_tables(apps, schema_editor):
    """Drop old research_* tables and clean up django_migrations."""
    cursor = schema_editor.connection.cursor()

    cursor.execute("DROP TABLE IF EXISTS research_citationverification CASCADE")
    cursor.execute("DROP TABLE IF EXISTS research_researchresult CASCADE")
    cursor.execute("DROP TABLE IF EXISTS research_researchquery CASCADE")

    cursor.execute("DELETE FROM django_migrations WHERE app = 'research'")


class Migration(migrations.Migration):

    dependencies = [
        ("case", "0047_researchquery_researchresult_citationverification"),
    ]

    operations = [
        migrations.RunPython(drop_old_research_tables, migrations.RunPython.noop),
    ]
