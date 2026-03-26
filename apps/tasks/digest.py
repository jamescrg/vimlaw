from datetime import timedelta

from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.calendar.models import Event
from apps.tasks.models import Task

LOOKAHEAD_DAYS = 3


def send_daily_digest():
    """Entry point called by Django-Q2 schedule.

    Queries all active users with digest_enabled=True and sends each
    a digest email summarising overdue, today, and upcoming items.
    """
    today = timezone.localdate()
    is_weekend = today.weekday() >= 5

    users = CustomUser.objects.filter(
        is_active=True,
        digest_enabled=True,
    ).exclude(Q(email="") | Q(email__isnull=True))

    for user in users:
        if is_weekend and not user.digest_include_weekends:
            continue
        send_digest_for_user(user)


def send_digest_for_user(user):
    """Build and send a single digest email for the given user.

    Returns True if an email was sent, False if there was nothing to report.
    Limited users (perm_all_matters=False) only see items for their matters.
    """
    today = timezone.localdate()
    upcoming_end = today + timedelta(days=LOOKAHEAD_DAYS)

    # Scope to user's matters if limited user
    matter_filter = {}
    if not user.perm_all_matters:
        user_matter_ids = list(user.assigned_matters.values_list("id", flat=True))
        matter_filter = {"matter__id__in": user_matter_ids}

    # Events
    events_qs = Event.objects.select_related("matter").filter(**matter_filter)

    overdue_events = events_qs.filter(
        date__lt=today,
        status="Pending",
    ).order_by("date", "start_time")

    today_events = events_qs.filter(
        date=today,
        status="Pending",
    ).order_by("start_time")

    upcoming_events = events_qs.filter(
        date__gt=today,
        date__lte=upcoming_end,
        status="Pending",
    ).order_by("date", "start_time")

    # Tasks
    tasks_qs = Task.objects.select_related("user", "matter").filter(**matter_filter)

    overdue_tasks = tasks_qs.filter(
        date_due__lt=today,
        status="Pending",
    ).order_by("date_due", "-priority")

    today_tasks = tasks_qs.filter(
        date_due=today,
        status="Pending",
    ).order_by("-priority")

    upcoming_tasks = tasks_qs.filter(
        date_due__gt=today,
        date_due__lte=upcoming_end,
        status="Pending",
    ).order_by("date_due", "-priority")

    has_content = (
        overdue_events.exists()
        or overdue_tasks.exists()
        or today_events.exists()
        or today_tasks.exists()
        or upcoming_events.exists()
        or upcoming_tasks.exists()
    )

    if not has_content:
        return False

    context = {
        "user": user,
        "today": today,
        "overdue_events": overdue_events,
        "overdue_tasks": overdue_tasks,
        "today_events": today_events,
        "today_tasks": today_tasks,
        "upcoming_events": upcoming_events,
        "upcoming_tasks": upcoming_tasks,
        "lookahead_days": LOOKAHEAD_DAYS,
    }

    html_message = render_to_string("emails/daily_digest.html", context)
    text_message = render_to_string("emails/daily_digest.txt", context)

    send_mail(
        subject=f"Daily Digest for {today.strftime('%A, %B %-d')}",
        message=text_message,
        from_email=None,
        recipient_list=[user.email],
        html_message=html_message,
    )

    return True
