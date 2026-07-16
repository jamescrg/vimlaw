from datetime import date
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter
from apps.settings.models import Firm


def build_fee_claim_context(matter: Matter, include_unclaimed: bool = False) -> dict:
    """
    Assemble the fee claim data for a matter, mirroring the Categories view:
    one section per category in drag order, each listing its time entries and
    expenses, plus a summary table and claimed/unclaimed/grand totals.

    Comp entries are listed (struck through) but every total is NET — the
    claim operates on the restriction that comped work can't be claimed.
    Unclaimed categories appear only when include_unclaimed is set; the
    uncategorized bucket counts as claimed or unclaimed per the matter's
    switch. Each entry has exactly one category, so nothing double-counts.
    """

    sections = []

    def add_section(title, claimed, time_entries, expenses):
        if not time_entries and not expenses:
            return
        fees_net = sum(e.fee for e in time_entries if not e.comp)
        expenses_net = sum(x.amount for x in expenses if not x.comp)
        sections.append(
            {
                "title": title,
                "claimed": claimed,
                "entries": time_entries,
                "expenses": expenses,
                "fees_net": fees_net,
                "expenses_net": expenses_net,
                "total": fees_net + expenses_net,
            }
        )

    for category in matter.activity_categories.all():  # position order
        if not category.claimed and not include_unclaimed:
            continue
        # Matter guard: a category left on an entry that later moved to
        # another matter can never leak into this matter's claim.
        add_section(
            category.name,
            category.claimed,
            list(category.time_entries.filter(matter=matter).order_by("date", "id")),
            list(category.expense_entries.filter(matter=matter).order_by("date", "id")),
        )

    if matter.uncategorized_claimed or include_unclaimed:
        add_section(
            "Uncategorized",
            matter.uncategorized_claimed,
            list(
                TimeEntry.objects.filter(matter=matter, category__isnull=True).order_by(
                    "date", "id"
                )
            ),
            list(
                ExpenseEntry.objects.filter(
                    matter=matter, activity_category__isnull=True
                ).order_by("date", "id")
            ),
        )

    def rollup(rows):
        fees = sum(s["fees_net"] for s in rows)
        expenses = sum(s["expenses_net"] for s in rows)
        return {"fees": fees, "expenses": expenses, "total": fees + expenses}

    claimed_sections = [s for s in sections if s["claimed"]]
    unclaimed_sections = [s for s in sections if not s["claimed"]]

    return {
        "matter": matter,
        "sections": sections,
        "claimed_totals": rollup(claimed_sections),
        "unclaimed_totals": rollup(unclaimed_sections),
        "grand_totals": rollup(sections),
        "has_unclaimed": bool(unclaimed_sections),
        "current_date": date.today(),
        "company": Firm.objects.first(),
    }


def generate_fee_claim_report(
    matter: Matter, request: WSGIRequest, include_unclaimed: bool = False
) -> NamedTemporaryFile:
    """
    Generate the fee claim report PDF — the exhibit to an attorney affidavit
    on a fee motion.
    """

    context = build_fee_claim_context(matter, include_unclaimed)

    html_string = render_to_string("matters/fee-claim-report.html", context)
    base_url = request.build_absolute_uri("/").rstrip("/")
    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
