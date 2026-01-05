from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("case", "0038_add_caselaw_include_in_ai"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE app_case_law
                DROP COLUMN IF EXISTS first_page,
                DROP COLUMN IF EXISTS parallel_page,
                DROP COLUMN IF EXISTS parallel_reporter,
                DROP COLUMN IF EXISTS parallel_volume,
                DROP COLUMN IF EXISTS reporter,
                DROP COLUMN IF EXISTS short_form,
                DROP COLUMN IF EXISTS volume;

                ALTER TABLE case_historicalcaselaw
                DROP COLUMN IF EXISTS first_page,
                DROP COLUMN IF EXISTS parallel_page,
                DROP COLUMN IF EXISTS parallel_reporter,
                DROP COLUMN IF EXISTS parallel_volume,
                DROP COLUMN IF EXISTS reporter,
                DROP COLUMN IF EXISTS short_form,
                DROP COLUMN IF EXISTS volume;
            """,
            reverse_sql="""
                ALTER TABLE app_case_law
                ADD COLUMN volume VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN reporter VARCHAR(50) NOT NULL DEFAULT '',
                ADD COLUMN first_page VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN parallel_volume VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN parallel_reporter VARCHAR(50) NOT NULL DEFAULT '',
                ADD COLUMN parallel_page VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN short_form VARCHAR(255) NOT NULL DEFAULT '';

                ALTER TABLE case_historicalcaselaw
                ADD COLUMN volume VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN reporter VARCHAR(50) NOT NULL DEFAULT '',
                ADD COLUMN first_page VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN parallel_volume VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN parallel_reporter VARCHAR(50) NOT NULL DEFAULT '',
                ADD COLUMN parallel_page VARCHAR(20) NOT NULL DEFAULT '',
                ADD COLUMN short_form VARCHAR(255) NOT NULL DEFAULT '';
            """,
        ),
    ]
