from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = (
        "Create or update the nightly auto-summary schedule. Times are "
        "America/New_York; nights when qcluster is down are skipped "
        "(catch_up is off)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--cron",
            default="30 2 * * *",
            help="Cron expression for the nightly run (default: 30 2 * * *)",
        )

    def handle(self, *args, **options):
        cron = options["cron"]
        schedule, created = Schedule.objects.update_or_create(
            name="auto-summary-nightly",
            defaults={
                "func": "apps.case.ai.auto_summary.refresh_auto_summaries",
                "schedule_type": Schedule.CRON,
                "cron": cron,
                "repeats": -1,
            },
        )

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{action} auto-summary-nightly schedule (cron: {cron})")
        )
