from django import template

from apps.settings.models import FirmProfile

register = template.Library()


@register.simple_tag
def get_firm():
    """
    Returns the singleton FirmProfile instance for use in templates.

    Usage:
        {% load firm_tags %}
        {% get_firm as firm %}
        {{ firm.name }}
    """
    return FirmProfile.get_instance()
