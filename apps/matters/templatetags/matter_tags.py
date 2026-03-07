from django import template

from apps.matters.models import Matter

register = template.Library()


@register.simple_tag
def get_open_matters():
    return Matter.objects.filter(status="Open").order_by("name")
