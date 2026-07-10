"""Email rendering helpers."""

import os
import re
from email.mime.image import MIMEImage
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.template.loader import render_to_string
from premailer import transform

# Content-ID under which attach_firm_logo embeds the logo; templates reference
# it as src="cid:firm-logo" via the logo_cid context value.
FIRM_LOGO_CID = "firm-logo"

# Trailing legal-entity designation to drop from the sender display name (a
# comma/space separator is required so e.g. "...Spa" isn't mistaken for one).
# Mirrors the firm_entity template filter's list.
_FIRM_SUFFIX_RE = re.compile(
    r"[\s,]+(?:P\.?L\.?L\.?C\.?|P\.?L\.?C\.?|L\.?L\.?C\.?|L\.?L\.?P\.?|"
    r"L\.?P\.?A\.?|P\.?C\.?|P\.?A\.?|Chartered)\s*$",
    re.IGNORECASE,
)


def _billing_display_name(company):
    """Display name for billing email headers: '<Firm> Billing' with the entity
    suffix (", LLC" etc.) dropped, or just 'Billing' when the firm has no name.
    Shared by From and Reply-To so they read identically in the client's inbox."""
    firm = _FIRM_SUFFIX_RE.sub("", getattr(company, "name", "") or "").strip()
    return f"{firm} Billing" if firm else "Billing"


def billing_from_email(company):
    """From header for client-facing billing email: '<Firm> Billing' as display
    name in front of BILLING_FROM_EMAIL — e.g. '"Craig Legal Billing" <billing@…>'.
    Replies route to the firm's billing address via Reply-To. Returns None when
    no address is configured (so the caller falls back to DEFAULT_FROM_EMAIL)."""
    address = parseaddr(settings.BILLING_FROM_EMAIL or "")[1]
    return formataddr((_billing_display_name(company), address)) if address else None


def billing_reply_to(company):
    """Reply-To for client-facing billing email: the firm's billing address
    carrying the same '<Firm> Billing' display name — e.g.
    '"Craig Legal Billing" <billing@…>' — so a client's reply captures a sensible
    contact name in their inbox. Address is Firm.billing_email, falling back to
    the firm email. Returns None when no address is configured."""
    address = ""
    if company:
        address = (company.billing_email or company.email or "").strip()
    if not address:
        return None
    return formataddr((_billing_display_name(company), address))


def firm_postal_address(company):
    """One-line postal address for email footers — a legitimacy signal spam
    filters explicitly weight on commercial/transactional mail. Empty string
    when the firm has no address configured (the footer is omitted)."""
    if not company:
        return ""
    city_line = " ".join(
        part
        for part in (
            f"{company.city}," if company.city else "",
            company.state or "",
            company.zip_code or "",
        )
        if part
    )
    parts = (company.address_line_1, company.address_line_2, city_line)
    return " · ".join(p.strip() for p in parts if p and p.strip())


def attach_firm_logo(email, company):
    """CID-embed the firm logo so the HTML alternative can render it inline.

    Media URLs are signed and expire (object storage), so hot-linking
    company.logo.url in an email would break once archived; embedding the
    bytes with a Content-ID keeps the logo rendering forever. The image is
    marked inline (multipart/related when there are no real attachments), so
    spam filters don't score it as a document attachment. Returns True when
    a logo was attached; failures (missing file) are silently skipped — the
    templates fall back to the firm-name text via the img alt/conditional.
    """
    logo = getattr(company, "logo", None)
    if not logo:
        return False
    try:
        with logo.open("rb") as f:
            image = MIMEImage(f.read())
    except (OSError, ValueError):
        return False
    image.add_header("Content-ID", f"<{FIRM_LOGO_CID}>")
    image.add_header(
        "Content-Disposition", "inline", filename=os.path.basename(logo.name)
    )
    if not email.attachments:
        # No document attachments: a related root renders cleanest. With a
        # PDF attached the root must stay mixed; clients resolve the cid
        # reference either way.
        email.mixed_subtype = "related"
    email.attach(image)
    return True


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
