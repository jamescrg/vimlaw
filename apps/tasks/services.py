"""Service functions for task operations."""

from difflib import SequenceMatcher
from typing import NamedTuple, Optional

from apps.matters.models import Matter

# Scoring thresholds for inferring a matter from a typed prefix.
_MATCH_THRESHOLD = 0.5  # minimum score to accept a match at all
_AMBIGUITY_MARGIN = 0.05  # a runner-up within this of the best => ambiguous
_FUZZY_WORD_RATIO = 0.8  # typo tolerance when comparing single words


class QuickTaskMatch(NamedTuple):
    """Outcome of resolving a quick-add description to a matter.

    status is one of:
        "resolved"  - confidently matched a single matter (in ``matter``)
        "admin"     - prefix was "admin"; intentionally no matter
        "ambiguous" - prefix matched several matters equally; not guessed
        "unmatched" - a prefix was typed but nothing matched; not guessed
        "sticky"    - no prefix typed; reused the previous task's matter
        "filter"    - no prefix and no previous matter; caller uses its filter
    """

    description: str
    matter: Optional[Matter]
    use_smart_matching: bool
    status: str
    prefix: str


def _score_name(prefix, name):
    """Score how well a typed prefix identifies a matter name (0..1).

    Prefers prefix-of-word matches over typo similarity, and earlier words
    over later ones, so "Brown" matches "Estate of Margaret Brown" and a short
    "Sm" still matches "Smith Estate". Returns 0 when nothing meaningful lines
    up.
    """
    name_l = (name or "").lower().strip()
    p = prefix.lower().strip()
    if not name_l or not p:
        return 0.0

    if name_l == p:
        return 1.0
    if name_l.startswith(p):
        return 0.9

    name_words = name_l.split()
    p_words = p.split()

    if len(p_words) == 1:
        # Prefix-of-word match against any word in the name.
        for i, word in enumerate(name_words):
            if word.startswith(p):
                # The first word is the strongest signal; later words a touch less.
                return 0.8 if i == 0 else 0.7
        # Typo tolerance against individual words. Lengths are comparable here,
        # so SequenceMatcher.ratio behaves well (unlike prefix-vs-full-name).
        best = max(
            (SequenceMatcher(None, p, w).ratio() for w in name_words),
            default=0.0,
        )
        return 0.65 if best >= _FUZZY_WORD_RATIO else 0.0

    # Multi-word prefix: every typed token should line up with a distinct word.
    used = set()
    matched = 0
    for tok in p_words:
        for i, word in enumerate(name_words):
            if i in used:
                continue
            if (
                word.startswith(tok)
                or SequenceMatcher(None, tok, word).ratio() >= _FUZZY_WORD_RATIO
            ):
                used.add(i)
                matched += 1
                break
    if matched == len(p_words):
        return 0.85
    if matched:
        return 0.4 * (matched / len(p_words))
    return 0.0


def _match_matter(prefix, matters_list):
    """Resolve a typed prefix to a single matter without guessing.

    Returns (matter, status) where status is "resolved", "ambiguous", or
    "unmatched". A near-tie between two different matters is reported as
    ambiguous rather than silently picking one.
    """
    scored = [(_score_name(prefix, name), matter) for name, matter in matters_list]
    scored = [pair for pair in scored if pair[0] >= _MATCH_THRESHOLD]
    if not scored:
        return None, "unmatched"

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best_matter = scored[0]

    if len(scored) > 1:
        runner_score, runner_matter = scored[1]
        if (
            runner_matter.pk != best_matter.pk
            and runner_score >= best_score - _AMBIGUITY_MARGIN
        ):
            return None, "ambiguous"

    return best_matter, "resolved"


def process_quick_task_description(description, last_matter_id=None):
    """Process a quick task description with intelligent matter matching.

    Supports two modes:
    1. Dash notation: "Matter - task description" resolves the prefix to a
       matter (or to no matter when the prefix is "admin", unrecognised, or
       ambiguous). It never falls back to the previous matter, so a typo can no
       longer silently misfile a task.
    2. No dash: reuses the previous quick task's matter ("sticky") so a run of
       tasks for the same matter can be typed without repeating its name.

    Args:
        description: The raw task description from user input.
        last_matter_id: The matter ID from the last quick task (or None).

    Returns:
        QuickTaskMatch: the cleaned description plus the matched matter and the
        status/prefix the caller can surface to the user.
    """
    description = description.strip()

    # Dash notation, e.g. "Smith Estate - review will".
    if "-" in description:
        prefix, remainder = description.split("-", 1)
        prefix = prefix.strip()
        description = remainder.strip()
        if description:
            description = description[0].upper() + description[1:]

        if prefix.lower() == "admin":
            return QuickTaskMatch(description, None, True, "admin", prefix)

        matters = Matter.objects.filter(status__in=["Pending", "Open"])
        matters_list = [(m.name, m) for m in matters]
        matched_matter, status = _match_matter(prefix, matters_list)
        return QuickTaskMatch(description, matched_matter, True, status, prefix)

    # No dash - reuse the last matter so repeated tasks stay together.
    if description:
        description = description[0].upper() + description[1:]

    if last_matter_id:
        try:
            matched_matter = Matter.objects.get(pk=last_matter_id)
            return QuickTaskMatch(description, matched_matter, True, "sticky", "")
        except Matter.DoesNotExist:
            pass

    return QuickTaskMatch(description, None, False, "filter", "")


# ── AI-entry validation ──────────────────────────────────────────────────────
# Shared by the agenda chat's create-tasks blocks and the tasks tab's AI
# command interface. Every resolver is forgiving: unresolvable input means
# None (or the fallback), never an exception.


def resolve_matter_name(name):
    """Exact-name (case-insensitive) match among Pending/Open matters."""
    if not name:
        return None
    return Matter.objects.filter(
        name__iexact=str(name).strip(),
        status__in=["Pending", "Open"],
    ).first()


def resolve_assignee_name(name, requesting_user):
    """Match a full name among active users; fall back to the requester."""
    if not name:
        return requesting_user
    from apps.accounts.models import CustomUser

    wanted = str(name).strip().lower()
    match = next(
        (
            u
            for u in CustomUser.objects.filter(is_active=True)
            if u.full_name.lower() == wanted
        ),
        None,
    )
    return match or requesting_user


def parse_due_date(value):
    """ISO date string to date; None on anything else."""
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def clamp_importance(value, default=4):
    """Coerce to the firm's 1-7 scale; default on garbage."""
    try:
        return min(max(int(value), 1), 7)
    except (TypeError, ValueError):
        return default


# ── Date-window quick filters ────────────────────────────────────────────────
# Shared by the tasks app and the matter Tasks tab, whose toolbars both carry
# the same date-preset dropdown over their respective session filters.


def next_workday(today):
    """Tomorrow, or Monday when tomorrow lands on the weekend."""
    from datetime import timedelta

    day = today + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def detect_filter_label(filter_data, today):
    """Reconcile the date-dropdown label from filter_data's date / has_due_date state.

    Lets the date dropdown stay truthful when a date setting comes from the
    modal: matches today / week / unscheduled / all presets exactly, otherwise
    returns "custom" so the dropdown shows "Custom range" instead of silently
    mislabeling the state as "All Tasks".
    """
    from datetime import timedelta

    has_due_date = str(filter_data.get("has_due_date", ""))
    date_due_min = filter_data.get("date_due_min", "")
    date_due_max = filter_data.get("date_due_max", "")

    if has_due_date.lower() == "false" and not date_due_min and not date_due_max:
        return "unscheduled"
    if not date_due_min and not date_due_max and has_due_date in ("", "None"):
        return "all"
    # Calendar weeks run Sunday through Saturday; weekday() is 6 for Sunday.
    week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    next_week_start = week_start + timedelta(days=7)
    next_week_end = next_week_start + timedelta(days=6)
    if (
        date_due_min == str(next_week_start)
        and date_due_max == str(next_week_end)
        and not has_due_date
    ):
        return "next_week"
    next_workday_s = str(next_workday(today))
    if (
        date_due_min == next_workday_s
        and date_due_max == next_workday_s
        and not has_due_date
    ):
        return "next_workday"
    if date_due_min:
        return "custom"
    if not date_due_max:
        return "custom"

    today_s = str(today)
    end_of_week_s = str(week_start + timedelta(days=6))
    next7_s = str(today + timedelta(days=6))
    if date_due_max == today_s and not has_due_date:
        return "today"
    if date_due_max == end_of_week_s and not has_due_date:
        return "week"
    if date_due_max == next7_s and not has_due_date:
        return "next7"
    return "custom"


def quick_date_filters(today):
    """The date dropdown's presets: filter_label -> date-dimension values.

    Quick filters only touch the date dimension. status is intentionally
    left alone so a "Complete" filter set via the modal isn't silently
    destroyed when the user clicks Today / This Week / etc.
    """
    from datetime import timedelta

    # Calendar week: Sunday through Saturday. weekday() is 6 for Sunday.
    week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    end_of_week = week_start + timedelta(days=6)

    return {
        "all": {
            "filter_label": "all",
            "date_due_min": "",
            "date_due_max": "",
            "has_due_date": "",
        },
        "unscheduled": {
            "filter_label": "unscheduled",
            "has_due_date": "false",
            "date_due_min": "",
            "date_due_max": "",
        },
        "today": {
            "filter_label": "today",
            "date_due_max": today.strftime("%Y-%m-%d"),
            "date_due_min": "",
            "has_due_date": "",
        },
        # A forward single-day window: tomorrow, skipping the weekend.
        "next_workday": {
            "filter_label": "next_workday",
            "date_due_min": next_workday(today).strftime("%Y-%m-%d"),
            "date_due_max": next_workday(today).strftime("%Y-%m-%d"),
            "has_due_date": "",
        },
        # Rolling seven-day window (today plus six), open-ended at the start
        # like today/week so overdue tasks stay visible.
        "next7": {
            "filter_label": "next7",
            "date_due_min": "",
            "date_due_max": (today + timedelta(days=6)).strftime("%Y-%m-%d"),
            "has_due_date": "",
        },
        "week": {
            "filter_label": "week",
            "date_due_min": "",
            "date_due_max": end_of_week.strftime("%Y-%m-%d"),
            "has_due_date": "",
        },
        # Unlike today/week (open-ended so overdue tasks stay visible), next
        # week is a forward window: both bounds are set.
        "next_week": {
            "filter_label": "next_week",
            "date_due_min": (end_of_week + timedelta(days=1)).strftime("%Y-%m-%d"),
            "date_due_max": (end_of_week + timedelta(days=7)).strftime("%Y-%m-%d"),
            "has_due_date": "",
        },
    }


def refresh_date_preset(filter_data, today):
    """Re-stamp a semantic date preset's date dimensions from today.

    filter_label is the source of truth: when it names a quick preset, the
    stored date_due_min/max + has_due_date are re-derived so "Today" always
    means today, however long ago it was clicked. "custom" (and unknown or
    missing labels) are left untouched. Returns a new dict; the input is not
    mutated.
    """
    presets = quick_date_filters(today)
    label = filter_data.get("filter_label")
    if label in presets:
        return {**filter_data, **presets[label]}
    return dict(filter_data)


def create_task_from_ai_entry(entry, requesting_user):
    """Create a Task from an AI-emitted entry dict; None when unusable."""
    from apps.tasks.constants import STATUS_PENDING
    from apps.tasks.models import Task

    description = str(entry.get("description") or "").strip()[:200]
    if len(description) < 4:
        return None

    return Task.objects.create(
        description=description,
        status=STATUS_PENDING,
        date_due=parse_due_date(entry.get("due")),
        importance=clamp_importance(entry.get("importance")),
        user=resolve_assignee_name(entry.get("user"), requesting_user),
        matter=resolve_matter_name(entry.get("matter")),
    )
