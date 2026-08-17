"""Case-briefing prompts and parsers for the research pipeline.

The abstract system prompt is the read-and-abstract design proven in the
retired AI-chat research mode (resurrected from that code's final state):
a Flash briefing agent reads the ENTIRE opinion and returns a compact
structured abstract, so the pipeline judges every case on its full text
instead of an excerpt window. Extended here with two machine-parseable
trailing sections (RELEVANCE VERDICT, KEY AUTHORITIES) that drive the
pipeline's relevance ranking and citation chasing.
"""

import re

RESEARCH_ABSTRACT_SYSTEM = """\
You are a careful legal research assistant briefing a case for an
attorney's outline. You are given a QUESTION PRESENTED and the FULL text
of one judicial opinion. Write a compact abstract with these sections:

CASE: name, citation, court, date.
POSTURE: procedural posture in one line.
VEHICLE: the exact statutory or procedural basis of the decision (the
statute AND subsection, rule, or motion type the court decided under).
If it differs from the vehicle the question presented implies, say so
here and again under CAUTIONS: a case decided under a different
subsection or motion type (for example, a motion-for-sanctions ruling
under OCGA 9-11-37(d) offered on a motion-to-compel fee question under
9-11-37(a)(4)) is not authority for this question without an explicit
distinction, and its rules must never be blended into this question's
vehicle.
HOLDING: the holding(s), each with a VERBATIM quotation of the court's
operative language in quotation marks. Never paraphrase inside quotes.
RELEVANCE: how the reasoning bears on the question presented, citing the
specific passages (quote the key sentences verbatim).
CAUTIONS: anything that limits the case (dicta, distinguishable facts,
partial dissents, later history noted in the text, slip-opinion or
not-yet-reported status).
SCOPE: one line listing other issues the opinion covers, so the reader
knows what else is in it.
RELEVANCE VERDICT: exactly one line reading "RELEVANCE VERDICT: HIGH" or
"RELEVANCE VERDICT: MODERATE" or "RELEVANCE VERDICT: LOW". HIGH only
when the opinion's holding bears directly on the question presented
under the same procedural vehicle. Always include this line, even when
the opinion is irrelevant.
KEY AUTHORITIES: up to 3 reporter citations, one per line, written
exactly as they appear in the opinion, of the earlier cases THIS opinion
rests its rule on for the question presented. Write "none" if the
opinion cites nothing load-bearing for this question.

Under 400 words plus quotations. If the opinion is genuinely irrelevant
to the question, say so in one line under RELEVANCE and keep the rest
minimal."""

# Refiner discipline: the query must be built from the question's exact
# procedural vehicle. This wording (with the 37(d)/37(a)(4) example)
# stopped the retired research chat from blending sanctions cases into
# motion-to-compel fee questions.
PROCEDURAL_VEHICLE_RULES = (
    "PROCEDURAL VEHICLE: before designing the query, state to yourself "
    "the exact procedural vehicle of the question - the statute AND "
    "subsection, rule, or motion type it arises under - and build the "
    "query from that vehicle's operative language. Cases decided under a "
    "different subsection or motion type (for example, a "
    "motion-for-sanctions ruling under OCGA 9-11-37(d) offered on a "
    "motion-to-compel fee question under 9-11-37(a)(4)) are not "
    "authority for the question; never blend the vehicles' terms into "
    "one query.\n\n"
)

_VERDICT_RE = re.compile(r"RELEVANCE VERDICT:\s*(HIGH|MODERATE|LOW)", re.IGNORECASE)
_KEY_AUTH_RE = re.compile(
    r"KEY AUTHORITIES:\s*(.+?)(?=\n[A-Z][A-Z ]{2,}:|\Z)", re.DOTALL
)
_RELEVANCE_RE = re.compile(r"\nRELEVANCE:\s*(.+?)(?=\n[A-Z][A-Z ]{2,}:|\Z)", re.DOTALL)

_VERDICT_MAP = {"high": "high", "moderate": "medium", "low": "low"}


def parse_brief(text):
    """Extract the machine-readable pieces of a structured abstract.

    Returns {"verdict": "high"|"medium"|"low", "key_authorities": [str],
    "reason": str}. A brief the parser can't read defaults to medium -
    never an error, the abstract text itself is still stored and shown.
    """
    text = text or ""

    verdict = "medium"
    match = _VERDICT_RE.search(text)
    if match:
        verdict = _VERDICT_MAP[match.group(1).lower()]

    authorities = []
    match = _KEY_AUTH_RE.search(text)
    if match:
        for line in match.group(1).splitlines():
            cite = line.strip().lstrip("-*•").strip()
            cite = re.sub(r"^\d+[.)]\s*", "", cite)
            if not cite or cite.lower().rstrip(".") == "none":
                continue
            authorities.append(cite)
            if len(authorities) == 3:
                break

    reason = ""
    match = _RELEVANCE_RE.search(text)
    if match:
        section = " ".join(match.group(1).split())
        sentence = re.split(r"(?<=[.!?])\s", section, maxsplit=1)[0]
        reason = sentence[:500]

    return {"verdict": verdict, "key_authorities": authorities, "reason": reason}
