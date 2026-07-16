from datetime import date
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.models import ActivityCategory
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter
from apps.settings.models import Firm


def build_fee_claim_context(matter: Matter) -> dict:
    """
    Assemble the fee claim data for a matter: one section per claimed
    category in position order, each with its time entries and
    gross / comp / net subtotals, plus the claim grand total. Each entry
    has exactly one category, so no entry can appear in two sections.
    """

    categories = ActivityCategory.objects.filter(matter=matter, claimed=True).order_by(
        "position", "name"
    )

    sections = []
    claim_gross = 0
    claim_comp = 0

    for category in categories:
        # Double filter (matter AND category) so a category left behind on
        # an entry that was later moved to another matter can never leak in.
        entries = TimeEntry.objects.filter(matter=matter, category=category).order_by(
            "date", "id"
        )
        if not entries:
            continue

        gross = sum(entry.fee for entry in entries)
        comp = sum(entry.fee for entry in entries if entry.comp)
        sections.append(
            {
                "category": category,
                "entries": entries,
                "gross": gross,
                "comp": comp,
                "net": gross - comp,
            }
        )
        claim_gross += gross
        claim_comp += comp

    return {
        "matter": matter,
        "sections": sections,
        "claim_gross": claim_gross,
        "claim_comp": claim_comp,
        "claim_total": claim_gross - claim_comp,
        "current_date": date.today(),
        "company": Firm.objects.first(),
    }


def generate_fee_claim_report(
    matter: Matter, request: WSGIRequest
) -> NamedTemporaryFile:
    """
    Generate the fee claim report PDF — the exhibit to an attorney affidavit
    on a fee motion.
    """

    context = build_fee_claim_context(matter)

    html_string = render_to_string("matters/fee-claim-report.html", context)
    base_url = request.build_absolute_uri("/").rstrip("/")
    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
