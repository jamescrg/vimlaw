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

# Recent-user-message words that make the witness protocol relevant; see
# FACTS_TRIGGER_RE in fact_blocks.py for the rationale.
WITNESS_TRIGGER_RE = re.compile(r"witness|testi|\brecord", re.IGNORECASE)

VALID_ALIGNMENTS = {value for value, _ in Witness.ALIGNMENT_CHOICES}

WITNESSES_PROTOCOL = """RECORDING WITNESSES. This matter has a stored witness list; its existing
entries appear in the context above. Only when the user explicitly
directs you to WRITE to that list ("add her as a witness", "record
these witnesses") end your reply with exactly one fenced block in this
form:

```create-witnesses
[{"name": "<full name>", "affiliation": "<the faction they belong to, or null>", "alignment": "neutral", "knowledge": "<what they know, saw, or would testify to, or null>", "phone": null, "email": null, "address": null, "importance": 4}]
```

Being asked to "list the witnesses", identify who might testify, or
discuss testimony is a request for PROSE in your reply, not direction
to write to the list: answer it in ordinary text and do not emit the
block. A person merely appearing in a document is not direction either.
Never emit the block unprompted; when unsure whether the user wants the
list updated, answer in prose and ask.

"affiliation" is the witness's group loyalty: the faction in the case
they belong to or align with. First work out the case's factions from
the materials and the existing witness list, then place the witness in
one, reusing the exact faction name already in use for their allies.
Often the factions are just "Plaintiff" and "Defendant", but name them
separately when parties are not aligned (for example co-defendants
blaming each other: "Defendant Smith", "Defendant Acme Corp."). Use
null when their loyalty is not yet clear. "alignment" is different:
friendly, neutral, or hostile toward our client's position, judged
from our client's side; use neutral when unclear (a witness can belong
to an opposing faction yet still be friendly on the facts).
"knowledge" is a short plain-language summary of what the witness can
speak to. Include phone, email, or address only when the materials
state them; never guess contact details. "importance" is the firm's
1-7 scale (4 = Normal). Never re-create a witness already listed
above."""


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
