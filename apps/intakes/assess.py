"""On-demand AI assessment of an intake (the Assessment tab).

The latest assessment lives on the Intake itself (assessment/assessed_at)
and is overwritten on each run; only the current read matters, so there is
no history. Running an assessment also adjusts the intake's importance
when the AI takes a position, and lists follow-up questions worth asking.
"""

import json
import logging

import markdown
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.intakes.models import Intake, Note
from apps.matters.models import PracticeArea

logger = logging.getLogger(__name__)

ASSESSMENT_TEXT_LIMIT = 50_000

ASSESSMENT_PROMPT = """You assess a prospective-client intake for a law firm and give the
reviewing attorney a frank read on whether it is worth pursuing.

The firm's practice areas: {area_names}.

Return ONLY a JSON object with this exact shape:
{{
  "summary": "<what the matter is, in 1-3 sentences>",
  "analysis": "<the analysis, in markdown>",
  "limitations": "<statute-of-limitations concern, or null>",
  "importance": <integer 1-7, or null>,
  "follow_up_questions": ["<question>", ...],
  "documents": ["<document worth collecting>", ...]
}}

Rules:
- "summary": what the matter is and what the prospective client wants,
  1-3 plain sentences.
- "analysis": whether the matter fits the firm, the apparent strengths and
  weaknesses of the caller's position, and anything that makes the
  engagement attractive or unattractive. Be frank and concise: as long as
  necessary and no longer. No filler, no hedging boilerplate, no restating
  the intake back at length.
- "importance": how promising this intake looks for the firm, on the
  firm's 1-7 scale (7 Highest, 6 Higher, 5 High, 4 Normal, 3 Low, 2 Lower,
  1 Lowest). Judge the substance, not the amount of detail: move above 4
  only on concrete positive signals (clearly fits the practice areas,
  meaningful amount in dispute, an apparently viable claim, genuine
  urgency); move below 4 only on concrete negative signals (outside the
  practice areas, no real legal dispute, apparently unviable position,
  signs of an undesirable engagement). Use null when there is too little
  information to justify moving off the current rating.
- "limitations": be particularly alert to statute-of-limitations and other
  deadline problems. When the facts suggest a limitations period may be
  running short or already missed, describe the concern and its urgency
  concisely here. Null when nothing stands out; do not force one.
- "follow_up_questions": the questions the firm should ask next to size up
  this matter, most useful first, at most 10. Factual questions only -
  things the caller would know firsthand. Never ask for documents,
  records, or paperwork here; those belong in "documents". Empty list
  when nothing meaningful is missing.
- "documents": the documents worth collecting from the prospective client
  to evaluate the matter (deeds, surveys, contracts, correspondence,
  photos, ...), most useful first, at most 10. Empty list when none come
  to mind.
- Return ONLY the JSON object, no other text, no markdown fences."""


def _intake_context(intake):
    """The intake's fields plus its full notes chronology, oldest first."""
    parts = [
        "INTAKE",
        f"Name: {intake.name}",
        f"Open date: {intake.date or ''}",
        f"Status: {intake.status}",
        f"Source: {intake.source or ''}",
        f"Practice area: {intake.practice_area.name if intake.practice_area else ''}",
        f"Phone: {intake.phone or ''}",
        f"Email: {intake.email or ''}",
        f"Address: {intake.address or ''}",
        f"Disputed property: {intake.disputed_property or ''}",
        f"Disputed value: {intake.value or ''}",
        f"Current importance: {intake.importance}",
        "",
        "NOTES CHRONOLOGY (oldest first)",
    ]
    notes = Note.objects.filter(intake=intake).order_by("date", "time", "id")
    for note in notes:
        author = note.user.username.title() if note.user else "Client"
        parts.append(
            f"[{note.date or ''} {note.time or ''}] {note.type or 'Note'}"
            f" ({author}):\n{note.details or ''}"
        )
    if not notes:
        parts.append("(no notes)")
    return "\n".join(parts)[:ASSESSMENT_TEXT_LIMIT]


def run_assessment(intake):
    """One AI call over everything on the intake. Updates assessment,
    assessed_at, and (when the AI takes a position) importance. Returns an
    error string on failure, leaving the stored assessment untouched."""
    from apps.case.ai.gemini_client import send_to_gemini

    area_names = ", ".join(
        PracticeArea.objects.filter(is_active=True).values_list("name", flat=True)
    )
    system_prompt = ASSESSMENT_PROMPT.format(area_names=area_names)

    try:
        response, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": _intake_context(intake)}]
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned.strip())
        summary = (data.get("summary") or "").strip()
        analysis = (data.get("analysis") or "").strip()
        if not summary and not analysis:
            raise ValueError("AI returned no assessment")
    except Exception as exc:
        logger.exception("Intake assessment failed")
        return str(exc)

    def clean_list(key):
        items = data.get(key) or []
        return [i.strip() for i in items if isinstance(i, str) and i.strip()][:10]

    sections = []
    if summary:
        sections.append(f"## Summary\n\n{summary}")
    if analysis:
        sections.append(f"## Analysis\n\n{analysis}")
    limitations = (data.get("limitations") or "").strip()
    if limitations:
        sections.append(f"## Statute of limitations\n\n{limitations}")
    questions = clean_list("follow_up_questions")
    if questions:
        # The blank line after the header matters: without it markdown runs
        # the header and items together into one paragraph
        numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
        sections.append(f"## Follow-up questions\n\n{numbered}")
    documents = clean_list("documents")
    if documents:
        bulleted = "\n".join(f"- {d}" for d in documents)
        sections.append(f"## Recommended documents\n\n{bulleted}")
    text = "\n\n".join(sections)

    try:
        intake.importance = min(max(int(data.get("importance")), 1), 7)
    except (TypeError, ValueError):
        pass

    intake.assessment = text
    intake.assessed_at = timezone.now()
    intake.save()
    return None


def assessment_html(intake):
    """The stored assessment rendered for the pane (notes render the same
    way in the detail views)."""
    return markdown.markdown(intake.assessment) if intake.assessment else ""


@login_required
@require_http_methods(["POST"])
def assess(request, id):
    """Run a fresh assessment and re-render the pane. On success the
    response also triggers a full detail refresh so the sidebar's
    importance flag catches up."""
    intake = get_object_or_404(Intake, pk=id)
    error = run_assessment(intake)
    response = render(
        request,
        "intakes/assessment.html",
        {
            "intake": intake,
            "assessment_html": assessment_html(intake),
            "assessment_error": error,
        },
    )
    if not error:
        response["HX-Trigger"] = "intakeDetailChanged"
    return response
