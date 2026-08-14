"""Token-authed JSON API over one matter's working record.

Consumed by the Claude Desktop MCP server (tools/kosmos_notes_mcp.py),
alongside the notes API in apps/notes/api.py. Reads serve every section
of a matter as AI-ready text, reusing the in-app chat's formatters where
they exist so the two surfaces cannot drift; writes are create-only
(timeline facts, witnesses, tasks) through the same validated entry
creators the in-app AI's fenced blocks use.

Access mirrors the app: matters are the user's accessible OPEN matters
only, and every denial is a 404 so it doesn't confirm existence.
"""

import json

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.access import filter_matters_for_user
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.time.models import TimeEntry
from apps.case.ai.context import (
    format_contacts,
    format_events,
    format_matter_overview,
    format_proceedings,
    format_settlement,
    format_tasks,
    format_witnesses,
)
from apps.case.ai.fact_blocks import _create_fact_from_entry
from apps.case.ai.witness_blocks import _create_witness_from_entry
from apps.case.models import Document, Fact, Highlight
from apps.drafts.api_auth import kosmos_api_auth
from apps.mail.ai import format_email_thread, group_by_thread, thread_subject
from apps.matters.models import Matter
from apps.matters.rates.models import Rate
from apps.tasks.services import create_task_from_ai_entry

MATTER_404 = "No such matter, or you do not have access to it."
DOCUMENT_404 = "No such document, or you do not have access to it."
THREAD_404 = "No such email thread in this matter."


def _get_matter(user, matter_id):
    """The matter, if it is open and accessible to user; None otherwise."""
    return (
        filter_matters_for_user(Matter.objects.filter(status="Open"), user)
        .filter(pk=matter_id)
        .first()
    )


def _json_body(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


# ---------------------------------------------------------------------------
# Section formatters not shared with the in-app chat context. These are
# manifest-shaped (ids and handles for follow-up tool calls) rather than
# chat-context-shaped, which is why they live here and not in ai/context.
# ---------------------------------------------------------------------------


def _format_rates(matter):
    """Billing setup: matter type plus hourly rates (matter overrides first)."""
    lines = [f"Billing type: {matter.get_billing_type_display()}"]
    if matter.billing_type == "FLAT_FEE" and matter.flat_fee_amount is not None:
        lines.append(f"Flat fee: ${matter.flat_fee_amount:,.2f}")
    if not matter.billable:
        lines.append("Matter is marked non-billable.")

    rates = list(
        Rate.objects.filter(Q(matter=matter) | Q(matter__isnull=True)).select_related(
            "user"
        )
    )
    matter_rows = [r for r in rates if r.matter_id]
    firm_rows = [r for r in rates if not r.matter_id]
    if matter_rows:
        lines.append("Rates for this matter (override the firm defaults):")
        lines += [f"- {r.user.full_name}: ${r.matter_rate}/hr" for r in matter_rows]
    if firm_rows:
        lines.append("Firm default rates:")
        lines += [f"- {r.user.full_name}: ${r.matter_rate}/hr" for r in firm_rows]
    if not matter_rows and not firm_rows:
        lines.append("No hourly rates set.")
    return "\n".join(lines)


def _format_activity(matter):
    """Time, expense, and flat-fee entries with category coding and totals."""
    sections = []

    entries = list(
        TimeEntry.objects.filter(matter=matter)
        .select_related("user", "invoice", "category")
        .order_by("-date")
    )
    if entries:
        lines = ["Time entries:"]
        total_hours = 0
        total_fees = 0
        for entry in entries:
            user_name = entry.user.get_full_name() if entry.user else "Unknown"
            fee = entry.hours * entry.rate if entry.rate else 0
            category = f" [{entry.category.name}]" if entry.category else ""
            line = (
                f"- [{entry.date}]{category} {entry.actions} — "
                f"{entry.hours}h @ ${entry.rate}/hr (${fee:,.2f}) by {user_name}"
            )
            if entry.comp:
                line += " [COMP]"
            if entry.invoice:
                line += f" [Invoice #{entry.invoice.id}, {entry.invoice.status}]"
            lines.append(line)
            total_hours += entry.hours
            if not entry.comp:
                total_fees += fee
        lines.append(f"Total: {total_hours}h, ${total_fees:,.2f} in non-comp fees")
        sections.append("\n".join(lines))

    expenses = list(
        ExpenseEntry.objects.filter(matter=matter)
        .select_related("activity_category", "invoice")
        .order_by("-date")
    )
    if expenses:
        lines = ["Expenses:"]
        for expense in expenses:
            category = (
                f" [{expense.activity_category.name}]"
                if expense.activity_category
                else ""
            )
            label = f"{expense.category}: " if expense.category else ""
            line = (
                f"- [{expense.date}]{category} {label}{expense.description} "
                f"(${expense.amount:,.2f})"
            )
            if expense.comp:
                line += " [COMP]"
            if expense.invoice:
                line += f" [Invoice #{expense.invoice.id}]"
            lines.append(line)
        total = sum(x.amount for x in expenses if not x.comp)
        lines.append(f"Total: ${total:,.2f} in non-comp expenses")
        sections.append("\n".join(lines))

    flat_fees = list(
        FlatFeeEntry.objects.filter(matter=matter)
        .select_related("invoice")
        .order_by("-date")
    )
    if flat_fees:
        lines = ["Flat fees:"]
        for fee in flat_fees:
            line = f"- [{fee.date}] {fee.description} (${fee.amount:,.2f})"
            if fee.comp:
                line += " [COMP]"
            if fee.invoice:
                line += f" [Invoice #{fee.invoice.id}]"
            lines.append(line)
        sections.append("\n".join(lines))

    return "\n\n".join(sections) or "No activity recorded."


def _format_documents(matter):
    """Document manifest: metadata only, never the extracted text."""
    documents = matter.documents.all()
    if not documents:
        return "No documents."
    lines = []
    for doc in documents:
        line = (
            f"- [doc:{doc.id}] {doc.name} ({doc.category}, "
            f"{doc.date or 'no date'}, importance {doc.importance})"
        )
        if doc.description:
            line += f"\n  {doc.description}"
        if doc.summary:
            line += f"\n  Summary: {doc.summary}"
        lines.append(line)
    lines.append("Use read_document with a doc id for a document's full text.")
    return "\n".join(lines)


def _format_highlights(matter):
    """Highlight manifest; [hl:ID] handles are valid add_fact sources."""
    highlights = Highlight.objects.filter(
        Q(document__matter=matter) | Q(caselaw__matter=matter)
    ).select_related("document", "caselaw")
    if not highlights:
        return "No highlights."
    lines = []
    for hl in highlights:
        text = hl.text if len(hl.text) <= 300 else hl.text[:300] + "..."
        lines.append(
            f'- [hl:{hl.id}] {hl.citation}: "{text}" '
            f"({hl.color}, importance {hl.importance})"
        )
    return "\n".join(lines)


def _format_facts(matter):
    """The timeline, oldest first, with linked source citations."""
    facts = (
        Fact.objects.filter(matter=matter)
        .order_by("date", "time")
        .prefetch_related("highlights", "documents")
    )
    if not facts:
        return "No timeline facts."
    lines = []
    for fact in facts:
        when = f"{fact.date or 'no date'}"
        if fact.time:
            when += f" {fact.time}"
        line = f"- [{when}] {fact.description} (importance {fact.importance})"
        sources = [hl.citation for hl in fact.highlights.all()[:3]]
        sources += [doc.name for doc in fact.documents.all()[:3]]
        if sources:
            line += f"\n  Sources: {', '.join(sources[:3])}"
        lines.append(line)
    return "\n".join(lines)


def _format_email_threads(matter):
    """Thread manifest: one line per Gmail thread, newest activity last."""
    threads = group_by_thread(matter.emails.dedup())
    if not threads:
        return "No synced emails."
    lines = []
    for emails in threads:
        key = emails[0].thread_id or emails[0].gmail_id
        first, last = emails[0], emails[-1]
        dates = ""
        if first.date and last.date:
            dates = (
                f", {first.date:%Y-%m-%d}"
                if len(emails) == 1
                else f", {first.date:%Y-%m-%d} to {last.date:%Y-%m-%d}"
            )
        senders = ", ".join(dict.fromkeys(e.sender_display for e in emails if e.sender))
        line = (
            f"- [thread {key}] {thread_subject(emails)} "
            f"({len(emails)} message{'s' if len(emails) != 1 else ''}{dates})"
        )
        if senders:
            line += f"\n  From: {senders}"
        if last.snippet:
            line += f"\n  Latest: {last.snippet[:150]}"
        lines.append(line)
    lines.append("Use read_email_thread with a thread id for the full thread.")
    return "\n".join(lines)


SECTIONS = {
    "overview": format_matter_overview,
    "contacts": format_contacts,
    "rates": _format_rates,
    "activity": _format_activity,
    "events": format_events,
    "tasks": format_tasks,
    "proceedings": format_proceedings,
    "settlement": format_settlement,
    "documents": _format_documents,
    "highlights": _format_highlights,
    "timeline": _format_facts,
    "witnesses": format_witnesses,
    "emails": _format_email_threads,
}


def _section_response(matter, section):
    return JsonResponse(
        {
            "matter_id": matter.id,
            "matter": matter.name,
            "section": section,
            "text": SECTIONS[section](matter),
        }
    )


@kosmos_api_auth
@require_GET
def api_matter_section(request, matter_id, section):
    """One section of a matter as AI-ready text."""
    matter = _get_matter(request.api_user, matter_id)
    if matter is None:
        return JsonResponse({"error": MATTER_404}, status=404)
    if section not in SECTIONS:
        return JsonResponse(
            {"error": f"Unknown section. Valid sections: {', '.join(SECTIONS)}."},
            status=400,
        )
    return _section_response(matter, section)


@kosmos_api_auth
@require_GET
def api_document(request, document_id):
    """One document's extracted text (the MCP client truncates)."""
    document = (
        Document.objects.select_related("matter")
        .filter(pk=document_id, matter__status="Open")
        .first()
    )
    if document is None or not request.api_user.has_matter_access(document.matter):
        return JsonResponse({"error": DOCUMENT_404}, status=404)
    return JsonResponse(
        {
            "id": document.id,
            "name": document.name,
            "matter": document.matter.name,
            "category": document.category,
            "date": str(document.date) if document.date else None,
            "ocr_status": document.ocr_status,
            "text": document.ocr_text or "",
        }
    )


@kosmos_api_auth
@require_GET
def api_email_thread(request, matter_id, thread_id):
    """One email thread in full, formatted like the in-app AI context."""
    matter = _get_matter(request.api_user, matter_id)
    if matter is None:
        return JsonResponse({"error": MATTER_404}, status=404)
    emails = list(
        matter.emails.filter(thread_id=thread_id)
        .dedup()
        .prefetch_related("attachment_files")
    )
    if not emails:
        return JsonResponse({"error": THREAD_404}, status=404)
    emails.sort(key=lambda e: e.date or e.created_at)
    return JsonResponse(
        {
            "thread_id": thread_id,
            "subject": thread_subject(emails),
            "text": format_email_thread(emails),
        }
    )


# ---------------------------------------------------------------------------
# Create-only writes, through the same entry creators the in-app AI's
# fenced blocks use (validation, matter scoping of cited ids, name dedup).
# GET on facts/ and witnesses/ serves the matching read section, so every
# documented section name works even though these paths are matched before
# the <str:section> route.
# ---------------------------------------------------------------------------


@kosmos_api_auth
@require_http_methods(["GET", "POST"])
def api_matter_facts(request, matter_id):
    """GET: the timeline section. POST: create one timeline fact."""
    matter = _get_matter(request.api_user, matter_id)
    if matter is None:
        return JsonResponse({"error": MATTER_404}, status=404)
    if request.method == "GET":
        return _section_response(matter, "timeline")

    entry = _json_body(request)
    if entry is None:
        return JsonResponse(
            {"error": "Request body must be a JSON object."}, status=400
        )
    fact = _create_fact_from_entry(entry, matter, request.api_user)
    if fact is None:
        return JsonResponse(
            {"error": "description is required (4-150 characters)."}, status=400
        )
    source_names = [hl.citation for hl in fact.highlights.all()[:3]]
    source_names += [doc.name for doc in fact.documents.all()[:3]]
    sources = f", source: {', '.join(source_names[:3])}" if source_names else ""
    return JsonResponse(
        {
            "id": fact.id,
            "message": (
                f"- Added to timeline: **{fact.description}**"
                f" ({fact.date or 'no date'}{sources})"
            ),
        },
        status=201,
    )


@kosmos_api_auth
@require_http_methods(["GET", "POST"])
def api_matter_witnesses(request, matter_id):
    """GET: the witnesses section. POST: create one witness (name-deduped)."""
    matter = _get_matter(request.api_user, matter_id)
    if matter is None:
        return JsonResponse({"error": MATTER_404}, status=404)
    if request.method == "GET":
        return _section_response(matter, "witnesses")

    entry = _json_body(request)
    if entry is None:
        return JsonResponse(
            {"error": "Request body must be a JSON object."}, status=400
        )
    witness, created = _create_witness_from_entry(entry, matter, request.api_user)
    if witness is None:
        return JsonResponse(
            {"error": "name is required (at least 2 characters)."}, status=400
        )
    if created:
        message = (
            f"- Added witness: **{witness.name}** ({witness.get_alignment_display()})"
        )
    else:
        message = f"- Already on the witness list: **{witness.name}**"
    return JsonResponse(
        {"id": witness.id, "created": created, "message": message},
        status=201 if created else 200,
    )


@kosmos_api_auth
@require_http_methods(["POST"])
def api_create_task(request):
    """Create one task, assigned to the token's user; matter optional.

    The matter is authorized here (create_task_from_ai_entry resolves by
    name with no access check), and re-pointed after creation in case a
    duplicate matter name resolved to a different matter.
    """
    entry = _json_body(request)
    if entry is None:
        return JsonResponse(
            {"error": "Request body must be a JSON object."}, status=400
        )

    matter = None
    if entry.get("matter_id") is not None:
        try:
            matter_id = int(entry["matter_id"])
        except (TypeError, ValueError):
            return JsonResponse({"error": MATTER_404}, status=404)
        matter = _get_matter(request.api_user, matter_id)
        if matter is None:
            return JsonResponse({"error": MATTER_404}, status=404)

    task = create_task_from_ai_entry(
        {
            "description": entry.get("description"),
            "due": entry.get("due"),
            "importance": entry.get("importance"),
            "matter": matter.name if matter else None,
        },
        request.api_user,
    )
    if task is None:
        return JsonResponse(
            {"error": "description is required (at least 4 characters)."}, status=400
        )
    if matter and task.matter_id != matter.id:
        task.matter = matter
        task.save(update_fields=["matter"])

    message = f"- Created task: **{task.description}**"
    if task.date_due:
        message += f" (Due: {task.date_due})"
    return JsonResponse(
        {
            "id": task.id,
            "matter": task.matter.name if task.matter else "Admin",
            "message": message,
        },
        status=201,
    )
