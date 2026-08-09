from django.core.management.base import BaseCommand

from apps.notes.models import get_library_notes
from apps.notes.tasks import generate_note_summary, queue_stale_library_summaries


class Command(BaseCommand):
    help = (
        "Generate AI summaries for library notes whose summary is missing or "
        "stale. Queues onto qcluster by default; --sync runs inline."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run summary generation inline instead of queueing to qcluster",
        )

    def handle(self, *args, **options):
        if options["sync"]:
            count = 0
            for note in get_library_notes():
                generate_note_summary(note.id)
                count += 1
            self.stdout.write(f"Processed {count} library notes inline")
        else:
            queued = queue_stale_library_summaries()
            self.stdout.write(f"Queued {queued} summary tasks")
