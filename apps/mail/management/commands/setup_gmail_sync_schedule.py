from croniter import croniter
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule


class Command(BaseCommand):
    help = (
        "Create or update the Gmail sync schedules: an incremental history "
        "sync every 2 minutes and a weekly full re-list (early Monday) to "
        "reconcile drift the history feed can't repair. No env gate: the "
        "sync is read-only and no-ops when google/email_tokens.json is "
        "empty, so dev inheriting these rows via the nightly prod-to-dev "
        "copy is harmless."
    )

    def handle(self, *args, **options):
        schedules = [
            ("gmail-sync", "apps.mail.google.scheduled_sync", "*/2 * * * *"),
            (
                "gmail-sync-weekly-full",
                "apps.mail.google.scheduled_sync_full",
                "15 3 * * 1",
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
