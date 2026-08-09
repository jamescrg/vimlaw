"""Witness creation from case AI chat.

The classic-path case chat worker appends WITNESSES_PROTOCOL to its
system context and runs apply_witness_blocks() over the response. The AI
proposes witnesses in a ```create-witnesses``` fenced block; each block
is replaced in the stored message with a confirmation list, so both the
user and the AI's later turns see what happened. A malformed block is
left as text and creates nothing (same contract as create-facts and the
agenda chat's create-tasks blocks).
"""

import json
import logging
import re

from apps.case.models import Witness

logger = logging.getLogger(__name__)

WITNESS_BLOCK_RE = re.compile(r"```create-witnesses\s*\n(.*?)```", re.DOTALL)

VALID_ALIGNMENTS = {value for value, _ in Witness.ALIGNMENT_CHOICES}

WITNESSES_PROTOCOL = """RECORDING WITNESSES. Only when the user explicitly directs you to add
witnesses to this matter's witness list, end your reply with exactly one
fenced block in this form:

```create-witnesses
[{"name": "<full name>", "affiliation": "<role, organization, or relationship to the case, or null>", "alignment": "neutral", "knowledge": "<what they know, saw, or would testify to, or null>", "phone": null, "email": null, "address": null, "importance": 4}]
```

A person merely appearing in a document is NOT direction to record a
witness - never emit the block unprompted. "alignment" is friendly,
neutral, or hostile, judged from our client's side; use neutral when
unclear. "knowledge" is a short plain-language summary of what the
witness can speak to. Include phone, email, or address only when the
materials state them; never guess contact details. "importance" is the
firm's 1-7 scale (4 = Normal). The matter's existing witnesses appear in
the context above; never re-create one already listed."""


def _create_witness_from_entry(entry, matter, requesting_user):
    """Create one Witness from a block entry.

    Returns (witness, created): (None, False) when the entry is unusable,
    (existing, False) when a same-named witness already exists in the
    matter. Strict on name; forgiving on the optional fields (a bad
    alignment or importance degrades to the field's default).
    """
    name = str(entry.get("name") or "").strip()[:255]
    if len(name) < 2:
        return None, False

    existing = Witness.objects.filter(matter=matter, name__iexact=name).first()
    if existing:
        return existing, False

    alignment = str(entry.get("alignment") or "").strip().lower()
    if alignment not in VALID_ALIGNMENTS:
        alignment = "neutral"

    email = str(entry.get("email") or "").strip()
    if "@" not in email:
        email = ""

    try:
        importance = int(entry.get("importance", 4))
    except (TypeError, ValueError):
        importance = 4
    importance = min(7, max(1, importance))

    witness = Witness.objects.create(
        matter=matter,
        user=requesting_user,
        name=name,
        affiliation=str(entry.get("affiliation") or "").strip()[:255],
        phone=str(entry.get("phone") or "").strip()[:50],
        email=email[:254],
        address=str(entry.get("address") or "").strip(),
        alignment=alignment,
        knowledge=str(entry.get("knowledge") or "").strip(),
        importance=importance,
    )
    return witness, True


def apply_witness_blocks(response_text, matter, requesting_user):
    """Create Witnesses from any create-witnesses blocks, replacing each
    block with a confirmation list. A malformed block is left as text and
    creates nothing; a same-named existing witness is reported instead of
    duplicated."""

    def replace(match):
        try:
            entries = json.loads(match.group(1).strip())
            if not isinstance(entries, list):
                raise ValueError("create-witnesses block is not a list")
        except (ValueError, TypeError):
            logger.warning("Unparseable create-witnesses block left in place")
            return match.group(0)

        lines = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            witness, created = _create_witness_from_entry(
                entry, matter, requesting_user
            )
            if witness is None:
                continue
            if created:
                lines.append(
                    f"- Added witness: **{witness.name}**"
                    f" ({witness.get_alignment_display()})"
                )
            else:
                lines.append(f"- Already on the witness list: **{witness.name}**")
        return "\n".join(lines) if lines else "(no witnesses created)"

    return WITNESS_BLOCK_RE.sub(replace, response_text)
