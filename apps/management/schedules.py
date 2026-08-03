"""Canonical Django-Q schedules for the application.

Keeping schedule definitions in one module gives every environment the same
idempotent setup path while preserving the small legacy setup commands as
backwards-compatible aliases.
"""

from dataclasses import dataclass

from croniter import croniter
from django.utils import timezone
from django_q.models import Schedule


@dataclass(frozen=True)
class ScheduleSpec:
    name: str
    func: str
    cron: str


def schedule_specs(auto_summary_time="30 1"):
    return (
        ScheduleSpec(
            "daily-digest", "apps.tasks.digest.send_daily_digest", "0 7 * * *"
        ),
        ScheduleSpec(
            "calendar-sync", "apps.calendar.sync.scheduled_sync", "*/2 * * * *"
        ),
        ScheduleSpec("drive-sync", "apps.drive.google.scheduled_sync", "* * * * *"),
        ScheduleSpec(
            "drive-sync-nightly-full",
            "apps.drive.google.scheduled_sync_full",
            "30 3 * * *",
        ),
        ScheduleSpec("gmail-sync", "apps.mail.google.scheduled_sync", "*/2 * * * *"),
        ScheduleSpec(
            "gmail-sync-weekly-full",
            "apps.mail.google.scheduled_sync_full",
            "15 3 * * 1",
        ),
        ScheduleSpec(
            "auto-summary-nightly",
            "apps.case.ai.auto_summary.scheduled_refresh_auto_summaries",
            f"{auto_summary_time} * * 0,2-6",
        ),
        ScheduleSpec(
            "auto-summary-weekly-rebuild",
            "apps.case.ai.auto_summary.scheduled_refresh_auto_summaries_full",
            f"{auto_summary_time} * * 1",
        ),
        ScheduleSpec(
            "auto-daily-plan",
            "apps.dash.agenda.scheduled_refresh_daily_plans",
            "45 2 * * *",
        ),
        ScheduleSpec(
            "chat-purge-weekly",
            "apps.case.ai.purge.scheduled_purge_closed_chats",
            "0 3 * * 0",
        ),
    )


def install_schedules(names=None, auto_summary_time="30 1"):
    """Create or update selected schedules and return ``(spec, created)`` pairs."""
    wanted = set(names) if names is not None else None
    local_now = timezone.localtime(timezone.now())
    results = []

    for spec in schedule_specs(auto_summary_time=auto_summary_time):
        if wanted is not None and spec.name not in wanted:
            continue
        _, created = Schedule.objects.update_or_create(
            name=spec.name,
            defaults={
                "func": spec.func,
                "schedule_type": Schedule.CRON,
                "cron": spec.cron,
                "repeats": -1,
                # Prevent a newly-created or changed schedule from firing as
                # soon as qcluster starts; wait for its next real cron slot.
                "next_run": croniter(spec.cron, local_now).get_next(type(local_now)),
            },
        )
        results.append((spec, created))

    return results
