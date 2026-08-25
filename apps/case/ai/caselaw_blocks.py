"""Saving researched authorities from AI chat.

Same contract as the create-facts blocks: the worker appends
CASELAW_PROTOCOL to the system context when the conversation points at
research work, and finalize_response runs apply_caselaw_blocks() over
the response. The AI proposes authorities in a ```save-caselaw``` fenced
block; each block is replaced in the stored message with a confirmation
list. A malformed block is left as text and saves nothing.

This is the authority-ledger half of the agent's CourtListener tools:
a verified case persists to the matter's Saved case law (with the
proposition it was cited for in the notes) instead of living only in
the conversation.
"""

import json
import logging
import re
from datetime import date as date_cls

from apps.case.models import CaseLaw

logger = logging.getLogger(__name__)

CASELAW_BLOCK_RE = re.compile(r"```save-caselaw\s*\n(.*?)```", re.DOTALL)

# Recent-user-message words that make the save protocol relevant.
CASELAW_TRIGGER_RE = re.compile(
    r"case ?law|authorit|precedent|research|opinions?\b|\bcite[sd]?\b|\bsave\b",
    re.IGNORECASE,
)

CASELAW_PROTOCOL = """SAVING RESEARCHED AUTHORITIES. This matter has a Saved case law library.
Only when the user explicitly directs you to SAVE authorities ("save
these cases", "add them to the case law", "keep what you found") end
your reply with exactly one fenced block in this form:

```save-caselaw
[{"cluster_id": 12345, "proposition": "<one sentence: what the case is cited for>", "court": "<court name from the search hit>"}]
```

One entry per case, cluster_id from the research tools; "court" is the
court's display name as the search hit showed it (omit if unknown). Only save cases
you actually read or searched inside this conversation and verified as
on point; never save a case from memory. "proposition" is the ledger
entry: the specific rule or holding the case supports, in one sentence.
Discussing or citing cases in your answer is NOT direction to save;
when unsure whether the user wants them saved, answer in prose and ask."""


def _save_entry(entry, matter, requesting_user):
    """Save one authority, or return None if the entry is unusable.

    Mirrors research_save_to_caselaws: the CaseLaw row is built from the
    cluster so citation-less slip opinions still save. An authority
    already in the library gets the proposition appended to its notes
    instead of a duplicate row ((matter, cluster_id) is unique).
    """
    from apps.case.courtlistener import fetch_cluster, format_citations_with_year
    from apps.case.research.tasks import generate_caselaw_summary

    try:
        cluster_id = int(entry.get("cluster_id") or 0)
    except (TypeError, ValueError):
        return None
    if not cluster_id:
        return None
    proposition = str(entry.get("proposition") or "").strip()[:500]

    existing = CaseLaw.objects.filter(matter=matter, cluster_id=cluster_id).first()
    if existing is not None:
        if proposition and proposition not in (existing.notes or ""):
            existing.notes = (
                f"{existing.notes}\n{proposition}" if existing.notes else proposition
            )
            existing.save(update_fields=["notes"])
        return existing

    cluster = fetch_cluster(cluster_id)
    if not cluster:
        return None

    date_filed = None
    if cluster.get("date_filed"):
        try:
            date_filed = date_cls.fromisoformat(cluster["date_filed"])
        except ValueError:
            date_filed = None

    # The cluster's "court" field is an API URL; keep the id from its tail.
    # The display name is not in the cluster, so the block may carry it
    # from the search hit; the id stands in when it does not.
    court_id = str(cluster.get("court") or "").rstrip("/").split("/")[-1]
    court_name = str(entry.get("court") or "").strip()[:255] or court_id

    opinion_id = None
    sub_opinions = cluster.get("sub_opinions", [])
    if sub_opinions:
        try:
            opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            opinion_id = None

    case_law = CaseLaw.objects.create(
        matter=matter,
        case_name=cluster.get("case_name") or f"Cluster {cluster_id}",
        citation=format_citations_with_year(cluster.get("citations", []), None),
        court=court_name,
        court_id=court_id,
        date_filed=date_filed,
        docket_number=str(cluster.get("docket_number") or ""),
        cluster_id=cluster_id,
        opinion_id=opinion_id,
        courtlistener_url=(
            f"https://www.courtlistener.com{cluster['absolute_url']}"
            if cluster.get("absolute_url")
            else ""
        ),
        notes=proposition,
        created_by=requesting_user,
        updated_by=requesting_user,
    )
    generate_caselaw_summary(case_law.id)
    return case_law


def apply_caselaw_blocks(response_text, matter, requesting_user):
    """Save authorities from any save-caselaw blocks, replacing each block
    with a confirmation list. A malformed block is left as text and saves
    nothing."""

    def replace(match):
        try:
            entries = json.loads(match.group(1).strip())
            if not isinstance(entries, list):
                raise ValueError("save-caselaw block is not a list")
        except (ValueError, TypeError):
            logger.warning("Unparseable save-caselaw block left in place")
            return match.group(0)

        lines = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            case_law = _save_entry(entry, matter, requesting_user)
            if case_law is not None:
                cite = f", {case_law.citation}" if case_law.citation else ""
                lines.append(f"- Saved to case law: **{case_law.case_name}**{cite}")
        return "\n".join(lines) if lines else "(no cases saved)"

    return CASELAW_BLOCK_RE.sub(replace, response_text)
