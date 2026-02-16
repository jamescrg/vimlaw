from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Create or update the daily digest email schedule"

    def handle(self, *args, **options):
        schedule, created = Schedule.objects.update_or_create(
            name="daily-digest",
            defaults={
                "func": "apps.agenda.tasks_digest.send_daily_digest",
                "schedule_type": Schedule.CRON,
                "cron": "0 7 * * *",
                "repeats": -1,
            },
        )

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{action} daily-digest schedule (cron: 0 7 * * *)")
        )
