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


def billing_from_email(company):
    """From header for client-facing billing email: the firm name (sans entity
    suffix) as display name in front of BILLING_FROM_EMAIL — e.g.
    '"Craig Legal" <billing@…>'. Replies route to the firm's billing address via
    Reply-To. Returns the bare address when there's no firm name, and None when
    no address is configured (so the caller falls back to DEFAULT_FROM_EMAIL)."""
    name = _FIRM_SUFFIX_RE.sub("", getattr(company, "name", "") or "").strip()
    address = parseaddr(settings.BILLING_FROM_EMAIL or "")[1]
    return formataddr((name, address)) if address else None


def billing_reply_to(company):
    """Reply-To for client-facing billing email: the firm's billing address
    carrying a '<Firm> Billing' display name — e.g.
    '"Craig Legal Billing" <billing@…>' — so a client's reply captures a sensible
    contact name in their inbox. Address is Firm.billing_email, falling back to
    the firm email. Returns None when no address is configured."""
    address = ""
    if company:
        address = (company.billing_email or company.email or "").strip()
    if not address:
        return None
    firm = _FIRM_SUFFIX_RE.sub("", getattr(company, "name", "") or "").strip()
    name = f"{firm} Billing" if firm else "Billing"
    return formataddr((name, address))


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
        # Keep `!important` so the dark-mode @media button override (which stays in
        # the <style> tag — media queries can't be inlined) still beats the inlined
        # light-mode value in clients that honour prefers-color-scheme.
        strip_important=False,
    )
