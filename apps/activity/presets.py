"""Date-window quick presets shared by the Activity tabs (time, expenses,
flat fees).

Same semantic mechanism as the tasks tab: filter_label is the source of
truth, and refresh_date_preset (apps.tasks.services) re-derives the stored
window from today on every read, so a session's "Today" or "This Week"
never goes stale. The Activity vocabulary is backward-looking (yesterday,
last week/month) where tasks' is forward-looking, so the preset dict lives
here; the refresh mechanism is shared.
"""

from datetime import timedelta


def activity_date_filters(today):
    """The Activity date dropdown's presets: filter_label -> filter values.

    Each preset only defines the fields it controls; the rest of the
    session filter (user, comp, matter, keyword, ...) is preserved by the
    callers. "unbilled" (Work in Progress) is date-free: it pins the
    entered/invoice dimensions instead.
    """
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    last_monday = monday - timedelta(days=7)
    last_sunday = monday - timedelta(days=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    return {
        "all": {"date_min": "", "date_max": "", "filter_label": "all"},
        "unbilled": {
            "date_min": "",
            "date_max": "",
            "entered": 0,
            "invoice": 0,
            "filter_label": "unbilled",
        },
        "today": {
            "date_min": str(today),
            "date_max": str(today),
            "filter_label": "today",
        },
        "yesterday": {
            "date_min": str(today - timedelta(days=1)),
            "date_max": str(today - timedelta(days=1)),
            "filter_label": "yesterday",
        },
        "this_week": {
            "date_min": str(monday),
            "date_max": str(today),
            "filter_label": "this_week",
        },
        "last_week": {
            "date_min": str(last_monday),
            "date_max": str(last_sunday),
            "filter_label": "last_week",
        },
        "this_month": {
            "date_min": str(month_start),
            "date_max": str(today),
            "filter_label": "this_month",
        },
        "last_month": {
            "date_min": str(last_month_start),
            "date_max": str(last_month_end),
            "filter_label": "last_month",
        },
    }


def detect_filter_label(filter_data, today):
    """Match filter_data's date / entered / invoice state to a quick preset.

    Lets the date dropdown stay truthful when dates come from the Filter
    modal: posted dates that match a preset window get that label (and so
    track forward semantically); otherwise "custom", which the refresh
    mechanism never touches.
    """
    date_min = filter_data.get("date_min", "")
    date_max = filter_data.get("date_max", "")
    entered = str(filter_data.get("entered", ""))
    invoice = str(filter_data.get("invoice", ""))

    if not date_min and not date_max:
        if entered == "0" and invoice == "0":
            return "unbilled"
        return "all"

    if not date_min or not date_max:
        return "custom"

    for label, preset in activity_date_filters(today).items():
        if (
            preset["date_min"]
            and date_min == preset["date_min"]
            and date_max == preset["date_max"]
        ):
            return label
    return "custom"
