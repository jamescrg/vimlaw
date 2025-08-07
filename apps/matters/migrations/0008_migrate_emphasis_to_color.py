from django.db import migrations


def migrate_emphasis_to_color(apps, schema_editor):
    Fact = apps.get_model('matters', 'Fact')
    Fact.objects.filter(emphasis='Yes').update(color='Yellow')


def reverse_migrate(apps, schema_editor):
    Fact = apps.get_model('matters', 'Fact')
    Fact.objects.filter(color='Yellow').update(emphasis='Yes')


class Migration(migrations.Migration):

    dependencies = [
        ('matters', '0007_add_color_field_to_fact'),
    ]

    operations = [
        migrations.RunPython(migrate_emphasis_to_color, reverse_migrate),
    ]