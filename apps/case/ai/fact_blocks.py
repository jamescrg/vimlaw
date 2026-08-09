"""Timeline fact creation from case AI chat.

The classic-path case chat worker appends FACTS_PROTOCOL to its system
context and runs apply_fact_blocks() over the response. The AI proposes
timeline entries in a ```create-facts``` fenced block; each block is
replaced in the stored message with a confirmation list, so both the user
and the AI's later turns see what happened. A malformed block is left as
text and creates nothing (same contract as the agenda chat's
create-tasks blocks).
"""

import json
import logging
import re
from datetime import (
    date as date_cls,
    time as time_cls,
)

from apps.case.models import Document, Fact

logger = logging.getLogger(__name__)

FACT_BLOCK_RE = re.compile(r"```create-facts\s*\n(.*?)```", re.DOTALL)

VALID_COLORS = {value for value, _ in Fact.COLOR_CHOICES if value}

FACTS_PROTOCOL = """RECORDING TIMELINE FACTS. This matter has a stored timeline table; its
existing facts appear in the context above. Only when the user
explicitly directs you to WRITE to that table ("add this to the
timeline", "record these facts", "put that on the timeline") end your
reply with exactly one fenced block in this form:

```create-facts
[{"date": "YYYY-MM-DD", "time": "HH:MM or null", "description": "<up to 150 chars>", "color": null, "importance": 4, "documents": [<doc ids>]}]
```

Being asked to "create a timeline", "build a chronology", or lay out
the sequence of events is a request for PROSE in your reply, not
direction to write to the table: answer it in ordinary text and do not
emit the block. Mentioning or noticing a date is not direction either.
Never emit the block unprompted; when unsure whether the user wants the
table updated, answer in prose and ask.

One entry per fact, in the order they should read. "description" is the
entire timeline row (150-char cap): state the event plainly, past
tense, no citations. "importance" is the firm's 1-7 scale (4 = Normal).
"color" tints the row; use null unless the user asks for one, otherwise
one of: Blue, Gray, Green, Orange, Purple, Red, Yellow. When a fact
comes from documents in the context, list their ids in "documents"
(taken from the [doc:ID] handles) so the timeline row links to its
sources; use [] when no document supports it, and never guess an id.
Never re-create a fact already in the timeline above."""


def _parse_date(value):
    if not value:
        return None
    try:
        return date_cls.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _parse_time(value):
    if not value:
        return None
    try:
        return time_cls.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _create_fact_from_entry(entry, matter, requesting_user):
    """Create one Fact from a block entry, or return None if it is unusable.

    Forgiving on the optional fields (a bad date, time, color, or
    importance degrades to the field's default) but strict on description,
    which is the row itself.
    """
    description = str(entry.get("description") or "").strip()
    if len(description) < 4:
        return None
    description = description[:150]

    color = str(entry.get("color") or "").strip().title() or None
    if color not in VALID_COLORS:
        color = None

    try:
        importance = int(entry.get("importance", 4))
    except (TypeError, ValueError):
        importance = 4
    importance = min(7, max(1, importance))

    fact = Fact.objects.create(
        matter=matter,
        user=requesting_user,
        date=_parse_date(entry.get("date")),
        time=_parse_time(entry.get("time")),
        description=description,
        color=color,
        importance=importance,
    )

    # Attach document sources, silently dropping ids that are not this
    # matter's documents (hallucinated or cross-matter ids must not link).
    raw_ids = entry.get("documents")
    if isinstance(raw_ids, list):
        doc_ids = []
        for value in raw_ids:
            try:
                doc_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if doc_ids:
            fact.documents.set(Document.objects.filter(matter=matter, id__in=doc_ids))

    return fact


def apply_fact_blocks(response_text, matter, requesting_user):
    """Create Facts from any create-facts blocks, replacing each block
    with a confirmation list. A malformed block is left as text and
    creates nothing."""

    def replace(match):
        try:
            entries = json.loads(match.group(1).strip())
            if not isinstance(entries, list):
                raise ValueError("create-facts block is not a list")
        except (ValueError, TypeError):
            logger.warning("Unparseable create-facts block left in place")
            return match.group(0)

        lines = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            fact = _create_fact_from_entry(entry, matter, requesting_user)
            if fact is not None:
                source_names = [doc.name for doc in fact.documents.all()[:3]]
                sources = f", source: {', '.join(source_names)}" if source_names else ""
                lines.append(
                    f"- Added to timeline: **{fact.description}**"
                    f" ({fact.date or 'no date'}{sources})"
                )
        return "\n".join(lines) if lines else "(no facts created)"

    return FACT_BLOCK_RE.sub(replace, response_text)
