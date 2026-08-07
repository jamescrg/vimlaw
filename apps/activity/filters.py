"""Helpers shared by the Activity tabs' FilterSets."""

from apps.matters.models import Matter


def include_selected_matter(filterset):
    """Ensure the bound matter is among the matter field's choices.

    "View in Activity Tab" on a closed matter files its id into the session
    filter, but the matter choices only carry Pending/Open/Complete. Without
    this, the bound form fails validation and django-filter silently drops
    the matter constraint, so the tab shows every matter's entries instead
    of the requested one. Appending the selected matter keeps the choice
    valid (and visible in the filter modal) whatever the matter's status.
    """
    try:
        matter_id = int((filterset.data or {}).get("matter"))
    except (TypeError, ValueError):
        return
    field = filterset.form.fields["matter"]
    if not field.queryset.filter(pk=matter_id).exists():
        field.queryset = (
            field.queryset | Matter.objects.filter(pk=matter_id)
        ).order_by("name")
