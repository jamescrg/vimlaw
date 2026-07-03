"""Template filters for invoicing display."""

import re

from django import template
from django.utils.html import conditional_escape

register = template.Library()

# Trailing legal-entity designations, most-specific first so e.g. "PLLC" isn't
# split into "P" + "LLC". A separator (comma/space) is required before the
# suffix, so a name like "...Spa" or "Tobacco" is never mistaken for one.
_ENTITY_RE = re.compile(
    r"^(.*\S)([\s,]+)("
    r"P\.?L\.?L\.?C\.?|P\.?L\.?C\.?|L\.?L\.?C\.?|L\.?L\.?P\.?|L\.?P\.?A\.?|"
    r"P\.?C\.?|P\.?A\.?|Chartered"
    r")\s*$",
    re.IGNORECASE,
)


@register.filter
def firm_strip(name):
    """Drop a trailing legal-entity designation (LLC, PLLC, P.C., LLP, PA, LPA,
    PLC, Chartered) from a firm name for client-facing display — e.g.
    "Craig Legal, LLC" -> "Craig Legal". Names with no recognized suffix pass
    through unchanged. HTML-escaped. Mirrors utils.mail's sender-name stripping."""
    if not name:
        return ""
    m = _ENTITY_RE.match(str(name).strip())
    if not m:
        return conditional_escape(name)
    # The greedy base group keeps the comma before the separator (a comma is
    # non-whitespace), so trim any trailing separator chars: "Craig Legal, LLC"
    # -> base "Craig Legal," -> "Craig Legal".
    return conditional_escape(re.sub(r"[\s,]+$", "", m.group(1)))
