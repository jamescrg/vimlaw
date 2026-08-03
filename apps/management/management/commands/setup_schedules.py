from django.core.management.base import BaseCommand

from apps.management.schedules import install_schedules


class Command(BaseCommand):
    help = "Create or update every recurring Django-Q schedule used by Kosmos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--auto-summary-time",
            default="30 1",
            help='Cron "minute hour" for nightly AI jobs (default: "30 1")',
        )

    def handle(self, *args, **options):
        results = install_schedules(auto_summary_time=options["auto_summary_time"])
        for spec, created in results:
            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{action} {spec.name} (cron: {spec.cron})")
            )

        self.stdout.write(
            self.style.SUCCESS(f"Configured {len(results)} recurring schedules.")
        )
