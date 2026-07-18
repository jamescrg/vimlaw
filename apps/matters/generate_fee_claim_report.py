from datetime import date
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter
from apps.matters.timekeepers import build_timekeepers
from apps.settings.models import Firm


def build_fee_claim_context(
    matter: Matter,
    include_unclaimed: bool = False,
    show_entries: bool = True,
    group_by_category: bool = True,
    reclaim_comp: bool = False,
) -> dict:
    """
    Assemble the fee claim data for a matter, mirroring the Categories view:
    one section per category in drag order, each listing its time entries and
    expenses, plus a summary table and claimed/unclaimed/grand totals.

    Comp entries are listed (struck through) but every total is NET — the
    claim operates on the restriction that comped work can't be claimed.
    Unclaimed categories appear only when include_unclaimed is set; the
    uncategorized bucket counts as claimed or unclaimed per the matter's
    switch. Each entry has exactly one category, so nothing double-counts.

    show_entries=False renders the summary alone; group_by_category=False
    keeps the summary but lists the entries chronologically in single
    Time Entries / Expenses tables, like the classic activity report.
    reclaim_comp=True claims comped work too: totals compute on gross and
    the template drops the struck-through treatment.
    """

    sections = []

    def add_section(title, claimed, time_entries, expenses):
        if not time_entries and not expenses:
            return
        fees_net = sum(e.fee for e in time_entries if reclaim_comp or not e.comp)
        expenses_net = sum(x.amount for x in expenses if reclaim_comp or not x.comp)
        sections.append(
            {
                "title": title,
                "claimed": claimed,
                "entries": time_entries,
                "expenses": expenses,
                "hours": sum(
                    e.hours for e in time_entries if reclaim_comp or not e.comp
                ),
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
        return {
            "hours": sum(s["hours"] for s in rows),
            "fees": fees,
            "expenses": expenses,
            "total": fees + expenses,
        }

    claimed_sections = [s for s in sections if s["claimed"]]
    unclaimed_sections = [s for s in sections if not s["claimed"]]

    timekeepers = build_timekeepers(matter, (e for s in sections for e in s["entries"]))

    # Ungrouped mode: one chronological run of everything included.
    all_entries = sorted(
        (e for s in sections for e in s["entries"]),
        key=lambda e: (e.date or date.min, e.id),
    )
    all_expenses = sorted(
        (x for s in sections for x in s["expenses"]),
        key=lambda x: (x.date or date.min, x.id),
    )

    return {
        "matter": matter,
        "sections": sections,
        "show_entries": show_entries,
        "group_by_category": group_by_category,
        "include_unclaimed": include_unclaimed,
        "all_entries": all_entries,
        "all_expenses": all_expenses,
        "timekeepers": timekeepers,
        "reclaim_comp": reclaim_comp,
        "claimed_totals": rollup(claimed_sections),
        "unclaimed_totals": rollup(unclaimed_sections),
        "grand_totals": rollup(sections),
        "has_unclaimed": bool(unclaimed_sections),
        "current_date": date.today(),
        "company": Firm.objects.first(),
    }


def generate_fee_claim_report(
    matter: Matter,
    request: WSGIRequest,
    include_unclaimed: bool = False,
    show_entries: bool = True,
    group_by_category: bool = True,
    reclaim_comp: bool = False,
) -> NamedTemporaryFile:
    """
    Generate the fee claim report PDF — the exhibit to an attorney affidavit
    on a fee motion.
    """

    context = build_fee_claim_context(
        matter, include_unclaimed, show_entries, group_by_category, reclaim_comp
    )

    html_string = render_to_string("matters/fee-claim-report.html", context)
    base_url = request.build_absolute_uri("/").rstrip("/")
    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
