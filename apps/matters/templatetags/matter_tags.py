from django import template

from apps.accounts.access import filter_matters_for_user
from apps.matters.models import Matter

register = template.Library()


@register.simple_tag(takes_context=True)
def get_open_matters(context):
    matters = Matter.objects.filter(status="Open").order_by("name")
    request = context.get("request")
    if request and hasattr(request, "user") and request.user.is_authenticated:
        matters = filter_matters_for_user(matters, request.user)
    return matters


@register.simple_tag(takes_context=True)
def get_adjacent_open_matters(context, matter):
    """The neighbours of ``matter`` on the open-matters list (the same
    name-ordered, per-user list the switcher dropdown shows), wrapping at the
    ends. Both None when the matter isn't on the list (closed, or filtered
    away for this user) — the detail toolbar hides its steppers then."""
    matters = list(get_open_matters(context))
    ids = [m.id for m in matters]
    if matter.id not in ids or len(matters) < 2:
        return {"prev": None, "next": None}
    i = ids.index(matter.id)
    return {"prev": matters[i - 1], "next": matters[(i + 1) % len(matters)]}
