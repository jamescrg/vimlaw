from croniter import croniter
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule


class Command(BaseCommand):
    help = (
        "Create or update the weekly chat-purge schedule (Sunday 03:00 "
        "local): deletes AI chat history for matters closed past the "
        "retention window. Run once on prod after deploy (same pattern as "
        "setup_auto_summary_schedule)."
    )

    def handle(self, *args, **options):
        cron = "0 3 * * 0"
        local_now = timezone.localtime(timezone.now())
        _, created = Schedule.objects.update_or_create(
            name="chat-purge-weekly",
            defaults={
                "func": "apps.case.ai.purge.scheduled_purge_closed_chats",
                "schedule_type": Schedule.CRON,
                "cron": cron,
                "repeats": -1,
                # A fresh row defaults next_run to now, which would fire the
                # schedule immediately; aim it at the real next slot.
                "next_run": croniter(cron, local_now).get_next(type(local_now)),
            },
        )
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} chat-purge-weekly ({cron})"))
