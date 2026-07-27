"""The shape of a custom intake form, and validation of the answers given to it.

A form's questions live in `FormTemplate.schema` — an ordered JSON list of field
objects. Two functions guard it:

- `normalize_schema` cleans a document posted by the builder before it is
  stored. It is the only thing that mints field keys.
- `validate_answers` cleans what a client typed, against the *snapshot* schema
  carried by their submission.

The key discipline that makes old submissions future-proof: every field carries
an immutable `key`, minted once from its label and never changed afterwards.
Answers are stored under that key, so relabelling a question — or reordering,
deleting, or adding others — never orphans an answer that was already given.
Option values work the same way for choice fields.
"""

import re
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.text import slugify

from config.helpers import normalize_phone

# Blocks that ask nothing — they structure the page but hold no answer.
LAYOUT_TYPES = frozenset({"heading", "text_block"})
# Fields whose answers must be drawn from a fixed option list.
CHOICE_TYPES = frozenset({"select", "radio", "checkboxes"})

MAX_FIELDS = 100
# Comfortably above a US states list (51) or a country list (~195) — those are
# ordinary dropdowns, not abuse. MAX_SCHEMA_BYTES is the real backstop.
MAX_OPTIONS = 250
MAX_LABEL = 200
MAX_HELP = 300
MAX_TEXT_BLOCK = 2000
# Request-body caps, checked by the views before json.loads so a hostile
# payload is never parsed.
MAX_SCHEMA_BYTES = 100 * 1024
MAX_ANSWERS_BYTES = 256 * 1024

_KEY_RE = re.compile(r"[a-z0-9_]{1,64}")


class SchemaError(ValueError):
    """A builder document that cannot be stored. The message is shown to staff."""


# --- Coercers for the type-specific keys -----------------------------------
#
# Each returns a cleaned value or raises; `_apply` falls back to the declared
# default rather than erroring, because a blank box in the builder is normal.


def _text(limit):
    def coerce(raw):
        return str(raw).strip()[:limit]

    return coerce


def _bounded_int(low, high):
    def coerce(raw):
        return max(low, min(high, int(raw)))

    return coerce


def _number(raw):
    """A numeric bound, kept as a canonical string so it drops straight into an
    HTML min/max attribute without float formatting artifacts."""
    value = Decimal(str(raw).strip())
    return format(value.normalize(), "f")


def _iso_date(raw):
    return date.fromisoformat(str(raw).strip()).isoformat()


def _truthy(raw):
    """Bare `bool()` is wrong for a posted flag: the builder sends JSON, and
    `bool("false")` is True. Treat the strings a select or a form would produce
    as the values they name."""
    if isinstance(raw, str):
        return raw.strip().lower() not in ("", "false", "no", "0", "off")
    return bool(raw)


def _apply(coerce, raw, default):
    if raw is None or raw == "":
        return default
    try:
        return coerce(raw)
    except (TypeError, ValueError, InvalidOperation):
        return default


# --- The field-type registry ------------------------------------------------
#
# `extra` maps each type-specific key to (coercer, default). It is the single
# source of truth for what a field object may contain: normalize_schema drops
# anything not declared here, so a hostile payload cannot smuggle extra data
# into the JSONField. `group` and `icon` drive the builder's palette.

_PLACEHOLDER = (_text(120), "")

FIELD_TYPES = {
    "text": {
        "label": "Short text",
        "group": "Questions",
        "icon": "icon-type",
        "input_type": "text",
        "extra": {
            "placeholder": _PLACEHOLDER,
            "max_length": (_bounded_int(1, 1000), 255),
        },
    },
    "select": {
        "label": "Dropdown",
        "group": "Questions",
        "icon": "icon-chevron-down",
        "input_type": "",
        "extra": {"placeholder": (_text(120), "Choose one…")},
    },
    "yesno": {
        "label": "Yes / No",
        "group": "Questions",
        "icon": "icon-toggle-left",
        "input_type": "",
        "extra": {},
    },
    "textarea": {
        "label": "Paragraph",
        "group": "Questions",
        "icon": "icon-align-left",
        "input_type": "",
        "extra": {
            "placeholder": _PLACEHOLDER,
            "rows": (_bounded_int(2, 20), 4),
            "max_length": (_bounded_int(1, 20000), 4000),
        },
    },
    "email": {
        "label": "Email",
        "group": "Questions",
        "icon": "icon-mail",
        "input_type": "email",
        "extra": {"placeholder": _PLACEHOLDER},
    },
    "phone": {
        "label": "Phone",
        "group": "Questions",
        "icon": "icon-phone",
        "input_type": "tel",
        "extra": {"placeholder": _PLACEHOLDER},
    },
    "number": {
        "label": "Number",
        "group": "Questions",
        "icon": "icon-hash",
        "input_type": "number",
        "extra": {
            "min": (_number, None),
            "max": (_number, None),
            "step": (_number, None),
        },
    },
    "currency": {
        "label": "Amount",
        "group": "Questions",
        "icon": "icon-dollar-sign",
        "input_type": "text",
        "extra": {"min": (_number, None), "max": (_number, None)},
    },
    "date": {
        "label": "Date",
        "group": "Questions",
        "icon": "icon-calendar",
        "input_type": "date",
        "extra": {"min": (_iso_date, None), "max": (_iso_date, None)},
    },
    "radio": {
        "label": "Radio buttons",
        "group": "Questions",
        "icon": "icon-circle-dot",
        "input_type": "",
        "extra": {},
    },
    "checkboxes": {
        "label": "Checkboxes",
        "group": "Questions",
        "icon": "icon-square-check",
        "input_type": "",
        "extra": {
            "min_selected": (_bounded_int(0, MAX_OPTIONS), 0),
            "max_selected": (_bounded_int(0, MAX_OPTIONS), 0),
        },
    },
    "heading": {
        "label": "Section heading",
        "group": "Layout",
        "icon": "icon-heading",
        "input_type": "",
        "extra": {},
    },
    "text_block": {
        "label": "Instructions",
        "group": "Layout",
        "icon": "icon-text",
        "input_type": "",
        "extra": {"text": (_text(MAX_TEXT_BLOCK), "")},
    },
}

# Palette display order. Layout leads: a form usually opens with a heading or
# an instruction block, so the first thing reached for sits first. One
# Questions group holds everything askable — the choice types are questions
# too — ordered most-reached-for first (dict order above is display order).
FIELD_GROUPS = ("Layout", "Questions")


def palette():
    """The builder's palette: one entry per field type, grouped for display."""
    return [
        {
            "group": group,
            "types": [
                {"type": name, "label": spec["label"], "icon": spec["icon"]}
                for name, spec in FIELD_TYPES.items()
                if spec["group"] == group
            ],
        }
        for group in FIELD_GROUPS
    ]


def blank_field(field_type):
    """A new field object of `field_type`, with every declared key at its
    default. `key` is null — the server mints it on save."""
    spec = FIELD_TYPES[field_type]
    field = {
        "key": None,
        "type": field_type,
        "label": "",
        "help": "",
        "required": False,
    }
    for name, (_coerce, default) in spec["extra"].items():
        field[name] = default
    if field_type in CHOICE_TYPES:
        field["options"] = []
    return field


def defaults():
    """`blank_field` for every type, for the builder to clone client-side."""
    return {name: blank_field(name) for name in FIELD_TYPES}


# --- Normalizing a posted builder document ---------------------------------


def new_key(label, taken):
    """Mint an immutable field key from a label.

    The random suffix means two questions with the same label still get
    distinct keys, and a duplicated field never collides with its original.
    """
    base = slugify(label or "").replace("-", "_")[:40].strip("_") or "field"
    while True:
        key = f"{base}_{secrets.token_hex(3)}"
        if key not in taken:
            return key


def _normalize_options(raw, position):
    if not isinstance(raw, list):
        raise SchemaError(f"Question {position} needs at least one option.")
    if len(raw) > MAX_OPTIONS:
        raise SchemaError(f"Question {position} has more than {MAX_OPTIONS} options.")
    options, taken = [], set()
    for option in raw:
        # The builder may hand us bare strings; a template seeded in code may too.
        if isinstance(option, str):
            option = {"label": option}
        if not isinstance(option, dict):
            raise SchemaError(f"Question {position} has a malformed option.")
        label = str(option.get("label") or "").strip()[:MAX_LABEL]
        if not label:
            # An empty row is what "add option" leaves behind until it's typed
            # into — dropping it is friendlier than refusing to save.
            continue
        value = option.get("value")
        if not (isinstance(value, str) and _KEY_RE.fullmatch(value)) or value in taken:
            value = new_key(label, taken)
        taken.add(value)
        options.append({"value": value, "label": label})
    if not options:
        raise SchemaError(f"Question {position} needs at least one option.")
    return options


def normalize_schema(raw):
    """Validate and coerce a builder document into canonical, storable form.

    Mints a key for any field lacking a valid unique one, drops keys the field's
    type doesn't declare, and raises `SchemaError` with a staff-readable message
    for anything it cannot repair.
    """
    if not isinstance(raw, list):
        raise SchemaError("The form is malformed.")
    if len(raw) > MAX_FIELDS:
        raise SchemaError(f"A form may have at most {MAX_FIELDS} questions.")

    schema, taken = [], set()
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SchemaError(f"Question {position} is malformed.")

        field_type = item.get("type")
        spec = FIELD_TYPES.get(field_type)
        if spec is None:
            raise SchemaError(f"Question {position} has an unknown type.")

        label = str(item.get("label") or "").strip()[:MAX_LABEL]
        if not label and field_type != "text_block":
            raise SchemaError(f"Question {position} needs a label.")

        # Keep the key the builder sent when it is well-formed and unclaimed —
        # that is what carries existing answers across an edit.
        key = item.get("key")
        if not (isinstance(key, str) and _KEY_RE.fullmatch(key)) or key in taken:
            key = new_key(label or field_type, taken)
        taken.add(key)

        field = {
            "key": key,
            "type": field_type,
            "label": label,
            "help": str(item.get("help") or "").strip()[:MAX_HELP],
            "required": _truthy(item.get("required"))
            and field_type not in LAYOUT_TYPES,
        }
        for name, (coerce, default) in spec["extra"].items():
            field[name] = _apply(coerce, item.get(name), default)
        if field_type in CHOICE_TYPES:
            field["options"] = _normalize_options(item.get("options"), position)
        schema.append(field)

    return schema


# --- Validating client answers ---------------------------------------------


def is_answered(value):
    """Whether a stored answer counts as given. False is a real answer to a
    yes/no question, so only None, blank strings and empty lists are empty."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return bool(value)
    return True


def _option_values(field):
    return {option["value"] for option in field.get("options") or []}


def _clean_one(field, raw):
    """Coerce one answer. Returns the cleaned value, or raises ValueError with
    a client-readable message."""
    field_type = field.get("type")

    if field_type == "yesno":
        if isinstance(raw, bool):
            return raw
        if str(raw).strip().lower() in ("true", "yes", "1"):
            return True
        if str(raw).strip().lower() in ("false", "no", "0"):
            return False
        raise ValueError("Choose Yes or No.")

    if field_type == "checkboxes":
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError("Malformed answer.")
        allowed = _option_values(field)
        # Silently drop values that aren't on the form — they can only come
        # from a tampered payload or a since-edited option list.
        return [v for v in raw if isinstance(v, str) and v in allowed]

    if field_type in ("select", "radio"):
        value = str(raw).strip()
        if not value:
            return ""
        if value not in _option_values(field):
            raise ValueError("Choose one of the listed options.")
        return value

    value = str(raw).strip()
    if not value:
        return ""

    if field_type in ("text", "textarea"):
        limit = field.get("max_length") or MAX_TEXT_BLOCK
        if len(value) > limit:
            raise ValueError(f"Please keep this under {limit} characters.")
        return value

    if field_type == "email":
        try:
            validate_email(value)
        except ValidationError:
            raise ValueError("Enter a valid email address.") from None
        return value

    if field_type == "phone":
        normalized, valid = normalize_phone(value)
        if not valid:
            raise ValueError("Enter a valid phone number.")
        return normalized

    if field_type in ("number", "currency"):
        try:
            number = Decimal(value.replace(",", "").lstrip("$"))
        except InvalidOperation:
            raise ValueError("Enter a number.") from None
        _check_bounds(field, number, lambda b: Decimal(b))
        return format(number, "f")

    if field_type == "date":
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("Enter a valid date.") from None
        _check_bounds(field, parsed, date.fromisoformat)
        return parsed.isoformat()

    return value


def _check_bounds(field, value, parse):
    low, high = field.get("min"), field.get("max")
    if low is not None and value < parse(low):
        raise ValueError(f"Must be {low} or more.")
    if high is not None and value > parse(high):
        raise ValueError(f"Must be {high} or less.")


def validate_answers(schema, answers, *, partial):
    """Coerce and validate client answers against a schema.

    Returns `(cleaned, errors)`. `cleaned` holds only keys that exist in the
    schema and survived coercion — it is what the caller merges into
    `FormSubmission.answers`, so a tampered payload cannot introduce keys.
    `errors` maps field key to a message.

    `partial=True` (autosave) skips required and min/max-selected checks, so a
    half-finished draft still saves. With `partial=False` the caller must pass
    the *complete* answer set (stored merged with incoming), because a required
    field is judged by what `answers` holds, not by what was just sent.
    """
    if not isinstance(answers, dict):
        return {}, {}

    cleaned, errors = {}, {}
    for field in schema or []:
        if not isinstance(field, dict) or field.get("type") in LAYOUT_TYPES:
            continue
        key = field.get("key")
        if not key:
            continue

        if key in answers:
            try:
                cleaned[key] = _clean_one(field, answers[key])
            except ValueError as exc:
                errors[key] = str(exc)
                continue

        if partial:
            continue

        value = cleaned.get(key)
        if field.get("required") and not is_answered(value):
            errors[key] = "This question is required."
            continue
        if field.get("type") == "checkboxes" and is_answered(value):
            count = len(value or [])
            low, high = field.get("min_selected") or 0, field.get("max_selected") or 0
            if low and count < low:
                errors[key] = f"Choose at least {low}."
            elif high and count > high:
                errors[key] = f"Choose at most {high}."

    return cleaned, errors
