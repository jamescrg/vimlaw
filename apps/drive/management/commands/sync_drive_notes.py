from datetime import datetime

from django.core.management.base import BaseCommand

import apps.drive.google as google


class Command(BaseCommand):
    help = (
        "Mirror PDFs under each matter's mapped Drive folders into Documents "
        "(append-only; categories and proceedings follow the Documents tab's "
        "Drive Folder mapping). The case-notes mirror is retired; files under "
        "Notes/ are ignored."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Force a full re-crawl instead of an incremental changes sync.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without downloading or writing files.",
        )

    def handle(self, *args, **options):
        stats = google.sync(
            dry_run=options["dry_run"],
            full=options["full"],
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if stats is None:
            self.stdout.write(
                self.style.WARNING(
                    "Drive sync skipped (no Drive account linked or root "
                    "folder not found)."
                )
            )
            return

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}✓ Drive sync completed at {timestamp}: {stats}"
            )
        )
