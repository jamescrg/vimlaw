from croniter import croniter
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule


class Command(BaseCommand):
    help = (
        "Create or update the auto-thread schedules: incremental refreshes "
        "six nights a week, a full rebuild early Monday (Sunday night). "
        "Times are America/New_York; nights when qcluster is down are "
        "skipped (catch_up is off)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--time",
            default="30 2",
            help='Cron "minute hour" for the nightly runs (default: "30 2")',
        )

    def handle(self, *args, **options):
        minute_hour = options["time"]

        schedules = [
            (
                "auto-summary-nightly",
                "apps.case.ai.auto_summary.refresh_auto_summaries",
                f"{minute_hour} * * 0,2-6",
            ),
            (
                "auto-summary-weekly-rebuild",
                "apps.case.ai.auto_summary.refresh_auto_summaries_full",
                f"{minute_hour} * * 1",
            ),
        ]

        local_now = timezone.localtime(timezone.now())
        for name, func, cron in schedules:
            _, created = Schedule.objects.update_or_create(
                name=name,
                defaults={
                    "func": func,
                    "schedule_type": Schedule.CRON,
                    "cron": cron,
                    "repeats": -1,
                    # A fresh row defaults next_run to now, which would fire
                    # the schedule immediately; aim it at the real next slot.
                    "next_run": croniter(cron, local_now).get_next(type(local_now)),
                },
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} {name} (cron: {cron})"))
