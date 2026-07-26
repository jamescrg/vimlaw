"""Turn a form schema plus its answers into something a template can loop over.

This is the only module that interprets a schema, and in practice it is always
handed a submission's `schema_snapshot` rather than a live template — which is
what makes an old submission render exactly as it was asked, forever. The
public fill page and the staff read view both come through here, so there is
one interpretation of a form and no second path to drift.
"""

import html
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.intakes.client_forms.schema import (
    CHOICE_TYPES,
    FIELD_TYPES,
    is_answered,
)


def _attrs(field):
    """HTML input attributes implied by the field's own spec, so the browser
    enforces the same bounds the server will."""
    attrs = {}
    for name in ("placeholder", "rows", "min", "max", "step"):
        value = field.get(name)
        if value not in (None, "", 0):
            attrs[name] = value
    if field.get("max_length"):
        attrs["maxlength"] = field["max_length"]
    return attrs


def _format_currency(value):
    try:
        return f"${Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return str(value)


def _format_date(value):
    try:
        return date.fromisoformat(str(value)).strftime("%B %-d, %Y")
    except ValueError:
        return str(value)


def answer_display(field, value):
    """One stored answer as staff-readable text — the option's label rather
    than its stored value, Yes/No for booleans, a formatted date or amount."""
    if not is_answered(value):
        return ""

    field_type = field.get("type")
    if field_type == "yesno":
        return "Yes" if value else "No"

    if field_type in CHOICE_TYPES:
        labels = {o["value"]: o["label"] for o in field.get("options") or []}
        if field_type == "checkboxes":
            # An option deleted from the template since answering has no label
            # left; show its stored value rather than dropping the answer.
            return ", ".join(labels.get(v, v) for v in value)
        return labels.get(value, str(value))

    if field_type == "currency":
        return _format_currency(value)
    if field_type == "date":
        return _format_date(value)
    return str(value)


def render_blocks(schema, answers=None, *, errors=None):
    """Ordered list of plain dicts, one per block in the schema.

    kind        "field" | "heading" | "text" | "unknown"
    type        the raw schema type
    key         stable field key ("" for layout blocks)
    label       staff-authored — templates must escape it, never |safe
    help        helper text
    text        body text, for kind == "text"
    required    bool
    input_type  HTML input type, for the simple single-input kinds
    attrs       placeholder / rows / min / max / step / maxlength
    options     [{value, label, selected}] for choice types
    value       the raw stored answer (None if unanswered)
    display     the answer as readable text ("" if unanswered)
    answered    bool
    error       validation message ("" if none)

    A type this build no longer recognizes yields kind "unknown" carrying its
    raw value, so retiring a field type never 500s an old submission.
    """
    answers = answers or {}
    errors = errors or {}
    blocks = []

    for field in schema or []:
        if not isinstance(field, dict):
            continue

        field_type = field.get("type")
        key = field.get("key") or ""
        value = answers.get(key)
        spec = FIELD_TYPES.get(field_type)

        block = {
            "kind": "field",
            "type": field_type,
            "key": key,
            "label": str(field.get("label") or ""),
            "help": str(field.get("help") or ""),
            "text": "",
            "required": bool(field.get("required")),
            "input_type": "",
            "attrs": {},
            "options": [],
            "value": None,
            "display": "",
            "answered": False,
            "error": errors.get(key, ""),
        }

        if spec is None:
            block["kind"] = "unknown"
            block["value"] = value
            block["answered"] = is_answered(value)
            block["display"] = str(value) if is_answered(value) else ""
        elif field_type == "heading":
            block["kind"] = "heading"
        elif field_type == "text_block":
            block["kind"] = "text"
            block["text"] = str(field.get("text") or "")
        else:
            block["input_type"] = spec["input_type"]
            block["attrs"] = _attrs(field)
            block["value"] = value
            block["answered"] = is_answered(value)
            block["display"] = answer_display(field, value)
            if field_type in CHOICE_TYPES:
                chosen = value if isinstance(value, list) else [value]
                block["options"] = [
                    {
                        "value": option["value"],
                        "label": option["label"],
                        "selected": option["value"] in chosen,
                    }
                    for option in field.get("options") or []
                ]

        blocks.append(block)

    return blocks


def orphan_answers(schema, answers):
    """Answers whose field is no longer in the schema, as (key, value) pairs.

    Only reachable if a submission's snapshot is ever rewritten — which nothing
    does today. Surfacing them beats dropping them silently.
    """
    known = {f.get("key") for f in schema or [] if isinstance(f, dict)}
    return [
        (key, ", ".join(map(str, value)) if isinstance(value, list) else str(value))
        for key, value in (answers or {}).items()
        if key not in known and is_answered(value)
    ]


# --- The answers as Markdown, for the intake's note timeline ---------------
#
# Note.details is run through markdown and emitted with |safe on the intake
# page, so anything a client typed would otherwise be live HTML there — a
# <script>, an onerror attribute, or a [link](javascript:...) all survive
# python-markdown untouched. Every answer therefore goes through _plain()
# below, which strips its power to be markup at all. The structure — headings,
# table pipes — is ours and stays live.

# Characters markdown gives meaning to. Escaped with a backslash, they render
# as themselves; `&`, `<` and `>` are handled by html.escape first.
_MD_SPECIALS = "\\`*_{}[]()#+-.!|~"


def _plain(text):
    """One piece of client text, rendered incapable of producing markup."""
    escaped = html.escape(str(text), quote=False)
    for char in _MD_SPECIALS:
        escaped = escaped.replace(char, "\\" + char)
    # A cell can't hold a newline; markdown tables are one row per line.
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def answered_blocks(blocks):
    """Only what the client actually said: unanswered questions drop out, and
    so does any heading left with nothing under it.

    Shared by the staff read view and the note Markdown so the two never
    disagree about what "what they submitted" means. How much went unanswered
    is already on the forms panel as a Done count, so a roll-call of blanks
    here would only bury the substance.
    """
    kept = []
    for block in blocks:
        if block["kind"] == "heading":
            kept.append(block)
            continue
        if block["kind"] in ("field", "unknown") and not block["answered"]:
            continue
        kept.append(block)

    # A heading with no answered block before the next heading says nothing.
    out = []
    for index, block in enumerate(kept):
        if block["kind"] == "heading":
            rest = kept[index + 1 :]
            following = next((b for b in rest if b["kind"] != "text"), None)
            if following is None or following["kind"] == "heading":
                continue
        out.append(block)
    return out


def submission_markdown(submission):
    """What the client said, as Markdown, for the note filed on submission."""
    blocks = answered_blocks(
        render_blocks(submission.schema_snapshot, submission.answers)
    )

    lines = [f"### {_plain(submission.template_name)}", ""]
    open_table = False
    wrote_any = False

    for block in blocks:
        if block["kind"] == "heading":
            lines += ["", f"#### {_plain(block['label'])}", ""]
            open_table = False
            continue
        if block["kind"] not in ("field", "unknown"):
            continue
        if not open_table:
            lines += ["| Question | Answer |", "| --- | --- |"]
            open_table = True
        lines.append(f"| {_plain(block['label'])} | {_plain(block['display'])} |")
        wrote_any = True

    if not wrote_any:
        lines.append("*No questions were answered.*")
    return "\n".join(lines).rstrip() + "\n"
