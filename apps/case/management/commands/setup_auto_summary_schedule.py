from django.core.management.base import BaseCommand

from apps.management.schedules import install_schedules


class Command(BaseCommand):
    help = (
        "Create or update the auto-thread schedules: incremental refreshes "
        "six nights a week, a full rebuild early Monday (Sunday night). "
        "Times are America/New_York; nights when qcluster is down are "
        "skipped (catch_up is off). The default 1:30am finishes well before "
        "the 08:30 UTC prod-to-dev copy in both EDT and EST, so dev wakes "
        "up with the fresh auto chats."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--time",
            default="30 1",
            help='Cron "minute hour" for the nightly runs (default: "30 1")',
        )

    def handle(self, *args, **options):
        minute_hour = options["time"]
        names = {
            "auto-summary-nightly",
            "auto-summary-weekly-rebuild",
            "auto-daily-plan",
        }
        for spec, created in install_schedules(
            names=names, auto_summary_time=minute_hour
        ):
            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{action} {spec.name} (cron: {spec.cron})")
            )
