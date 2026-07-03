"""Email rendering helpers."""

import re
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.template.loader import render_to_string
from premailer import transform

# Trailing legal-entity designation to drop from the sender display name (a
# comma/space separator is required so e.g. "...Spa" isn't mistaken for one).
# Mirrors the firm_entity template filter's list.
_FIRM_SUFFIX_RE = re.compile(
    r"[\s,]+(?:P\.?L\.?L\.?C\.?|P\.?L\.?C\.?|L\.?L\.?C\.?|L\.?L\.?P\.?|"
    r"L\.?P\.?A\.?|P\.?C\.?|P\.?A\.?|Chartered)\s*$",
    re.IGNORECASE,
)


def firm_from_email(company):
    """From header that shows the firm as sender: the firm name (sans entity
    suffix) as display name in front of the no-reply address — e.g.
    '"Craig Legal" <no-reply@…>'. Replies still route to the firm via Reply-To.
    Falls back to DEFAULT_FROM_EMAIL (None) when there's no firm name."""
    name = _FIRM_SUFFIX_RE.sub("", getattr(company, "name", "") or "").strip()
    address = parseaddr(settings.DEFAULT_FROM_EMAIL or "")[1]
    return formataddr((name, address)) if name and address else None


def render_inlined(template_name, context):
    """Render an HTML email template and inline its ``<style>`` CSS onto the
    elements (premailer). Mail clients strip external stylesheets and only
    unreliably honour ``<style>`` blocks, so inline ``style=""`` is what renders
    everywhere — this lets us author emails with a normal stylesheet and inline at
    send time. The ``<style>`` block is kept too, so ``@media`` rules (which can't
    be inlined) still drive responsive behaviour where supported.
    """
    html = render_to_string(template_name, context)
    return transform(
        html,
        keep_style_tags=True,
        # Never touch the network. All CSS is in the local <style> block; without
        # this premailer would try to DOWNLOAD external <link> stylesheets (e.g.
        # the Google Fonts link), blocking the send — and hanging it if the host
        # can't reach them. The font <link> is left in place for the mail client.
        allow_network=False,
        disable_validation=True,  # don't let cssutils drop modern CSS (gradients)
        cssutils_logging_level="CRITICAL",
    )
