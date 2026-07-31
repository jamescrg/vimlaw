from datetime import datetime

from django.core.management.base import BaseCommand

import apps.mail.google as google


class Command(BaseCommand):
    help = "Sync labeled Gmail messages onto their mapped matters"

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Force a full per-label re-list instead of an incremental "
            "history sync.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        stats = google.sync(dry_run=options["dry_run"], full=options["full"])

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if stats is None:
            self.stdout.write(
                self.style.WARNING(
                    "Gmail sync skipped (no Gmail account linked or no matters "
                    "mapped to a label)."
                )
            )
            return

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}✓ Gmail sync completed at {timestamp}: {stats}"
            )
        )
        if stats.get("missing_labels"):
            self.stdout.write(
                self.style.WARNING(
                    f"Mapped labels missing in Gmail: {stats['missing_labels']} "
                    "(relink the affected matters from their Emails tab)."
                )
            )
