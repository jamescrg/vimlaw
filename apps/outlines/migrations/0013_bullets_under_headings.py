"""
Data migration to enforce "bullets under headings must be children" rule.

Any top-level bullet that appears after a heading is moved to be a child
of that heading.
"""

from django.db import migrations


def fix_bullets_under_headings(apps, schema_editor):
    """Move top-level bullets after a heading to be children of that heading."""
    Outline = apps.get_model("outlines", "Outline")
    OutlineItem = apps.get_model("outlines", "OutlineItem")

    for outline in Outline.objects.all():
        current_heading = None
        items_to_update = []

        # Get root items ordered by 'order'
        root_items = OutlineItem.objects.filter(
            outline=outline, parent__isnull=True
        ).order_by("order")

        for item in root_items:
            if item.heading:
                # This is a heading - subsequent bullets become its children
                current_heading = item
            elif current_heading:
                # This bullet should be a child of current_heading
                items_to_update.append((item, current_heading))

        # Update items (need to reorder within each heading's children)
        heading_child_counts = {}
        for item, heading in items_to_update:
            if heading.id not in heading_child_counts:
                # Count existing children
                existing = OutlineItem.objects.filter(parent=heading).count()
                heading_child_counts[heading.id] = existing

            item.parent = heading
            item.order = heading_child_counts[heading.id]
            item.save()
            heading_child_counts[heading.id] += 1


def reverse_migration(apps, schema_editor):
    """No-op reverse - we can't reliably restore original structure."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("outlines", "0012_heading_boolean_to_integer"),
    ]

    operations = [
        migrations.RunPython(fix_bullets_under_headings, reverse_migration),
    ]
