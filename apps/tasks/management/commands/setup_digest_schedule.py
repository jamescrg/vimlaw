from django.core.management.base import BaseCommand

from apps.management.schedules import install_schedules


class Command(BaseCommand):
    help = "Create or update the daily digest email schedule"

    def handle(self, *args, **options):
        spec, created = install_schedules(names={"daily-digest"})[0]
        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{action} {spec.name} schedule (cron: {spec.cron})")
        )
