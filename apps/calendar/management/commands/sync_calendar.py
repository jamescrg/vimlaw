from datetime import datetime

from django.core.management.base import BaseCommand

from apps.calendar import sync


class Command(BaseCommand):
    help = "Sync events with Google Calendar (two-way sync)"

    def handle(self, *args, **options):
        self.stdout.write("Starting Google Calendar sync...")

        try:
            # Push local changes + drain queued deletions first, so local
            # removals reach Google before the pull (which would otherwise
            # re-create them) and any previously failed pushes get retried.
            result = sync.scheduled_sync()
            self.stdout.write(f"Reconciled local changes: {result['reconciled']}")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Google Calendar sync completed successfully at {timestamp}"
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Sync failed: {e}"))
            raise
