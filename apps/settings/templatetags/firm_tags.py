from django import template

from apps.settings.models import Firm

register = template.Library()


@register.inclusion_tag("components/auth-brand.html")
def auth_brand():
    """The auth-card title block (login, password reset, error pages): the
    firm's uploaded logo when one is set, the Kosmos wordmark otherwise.

    Swallows every lookup failure because the 500 page renders through
    this tag - when the database is the thing that's down, the brand
    block must still degrade to the wordmark instead of raising."""
    logo_url = ""
    firm_name = ""
    try:
        firm = Firm.objects.first()
        if firm:
            firm_name = firm.name
            if firm.logo:
                logo_url = firm.logo.url
    except Exception:
        pass
    return {"logo_url": logo_url, "firm_name": firm_name}
