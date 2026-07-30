"""Natural-language quick add, interpreted by Gemini Flash.

interpret_quick_add() turns the quick-add input's one typed line into a
single create entry (description, matter, assignee, due, importance),
resolved against the firm's real matter and team names. The caller
(tasks_add_quick) validates the entry with the shared resolvers in
services.py and falls back to the legacy prefix matcher when the AI is
unavailable or the reply is unusable.
"""

import json
import logging
import re

from django.utils import timezone

from apps.matters.models import Matter

logger = logging.getLogger(__name__)

QUICK_ADD_PROMPT = """You turn one line of plain language into a task entry.
Reply with ONLY a bare JSON object, no code fences, in this form:

{"description": "<what to do, 4-200 chars>", "matter": "<exact matter name or null>", "user": "<team member full name or null>", "due": "YYYY-MM-DD or null", "importance": <1-7 or null>}

Rules:
- Null means "the user did not say"; the system fills sensible defaults.
  Only fill a field the command actually states or clearly implies.
- Matter names and team member names must come verbatim from the lists
  below; when nothing matches clearly, use null.
- Resolve relative dates from today's date below. "Friday" means the next
  upcoming Friday.
- "high priority" is 6, "urgent" or "critical" is 7, "low priority" is 2.
- The description is what remains after removing matter, assignee, date,
  and priority phrasing. Keep the user's wording; fix nothing else.
"""


def _today_line():
    today = timezone.localdate()
    return f"Today is {today.strftime('%A')}, {today.isoformat()}."


def _matter_lines():
    names = (
        Matter.objects.filter(status__in=["Pending", "Open"])
        .order_by("name")
        .values_list("name", flat=True)
    )
    return "## Matters (Pending and Open)\n" + "\n".join(f"- {n}" for n in names)


def interpret_quick_add(text, user, recent_matter=None):
    """One quick-add line to a create-entry dict; None when unusable."""
    from apps.case.ai.context import build_request_info
    from apps.case.ai.gemini_client import send_to_gemini

    hint = ""
    if recent_matter:
        hint = (
            f"\nThe user's previous quick-add used the matter "
            f"'{recent_matter}'. Use it only if the new command clearly "
            f"continues that context without naming a matter.\n"
        )
    system_context = "\n".join(
        [
            build_request_info(user),
            QUICK_ADD_PROMPT,
            hint,
            _today_line(),
            "",
            _matter_lines(),
        ]
    )
    response, _, _ = send_to_gemini(
        system_context=system_context,
        messages=[{"role": "user", "content": text}],
        model="gemini-2.5-flash",
    )
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.strip())
    try:
        entry = json.loads(cleaned)
    except (ValueError, TypeError):
        logger.warning("Quick-add AI reply was not JSON")
        return None
    if not isinstance(entry, dict) or not entry.get("description"):
        return None
    return entry
