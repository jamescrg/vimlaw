from django.core.management.base import BaseCommand

from apps.dash.agenda import refresh_daily_plans


class Command(BaseCommand):
    help = (
        "Queue overnight daily-plan generation for every active user on "
        "demand (any environment; qcluster must be running). Best run after "
        "run_auto_summaries so plans draw on fresh matter threads."
    )

    def handle(self, *args, **options):
        queued = refresh_daily_plans()
        self.stdout.write(self.style.SUCCESS(f"Queued plans for {queued} user(s)"))
