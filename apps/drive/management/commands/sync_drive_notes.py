from datetime import datetime

from django.core.management.base import BaseCommand

import apps.drive.google as google


class Command(BaseCommand):
    help = (
        "Mirror Google Drive case notes (Matters - Open/*/Notes) to Markdown "
        "and linked record folders' PDFs to Record Documents (append-only)."
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
        parser.add_argument(
            "--debug-dir",
            default=None,
            help="Also write converted Markdown to this directory for inspection "
            "(overrides DRIVE_NOTES_DEBUG_DIR for this run).",
        )

    def handle(self, *args, **options):
        stats = google.sync(
            dry_run=options["dry_run"],
            full=options["full"],
            debug_dir=options["debug_dir"],
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if stats is None:
            self.stdout.write(
                self.style.WARNING(
                    "Drive case-notes sync skipped (no Drive account linked or "
                    "root folder not found)."
                )
            )
            return

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}✓ Drive case-notes sync completed at {timestamp}: {stats}"
            )
        )
