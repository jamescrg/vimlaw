"""Remove document records whose files are missing from storage."""

from django.core.management.base import BaseCommand
from django.db import connection

from apps.case.models import Document, Highlight


class Command(BaseCommand):
    help = "Delete document records whose files are missing from storage"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List orphan documents without deleting them",
        )

    def _clear_outline_references(self, highlight_ids):
        """Remove references from outlines tables that lack CASCADE."""
        if not highlight_ids:
            return
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM outlines_outlineitem_highlights "
                "WHERE highlight_id = ANY(%s)",
                [list(highlight_ids)],
            )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        orphans = []

        for doc in Document.objects.all().order_by("id"):
            try:
                exists = bool(doc.file) and doc.file.storage.exists(doc.file.name)
            except Exception:
                exists = False

            if not exists:
                orphans.append(doc)
                self.stdout.write(f"  ORPHAN  ID={doc.id}  {doc.file.name}")

        if not orphans:
            self.stdout.write(self.style.SUCCESS("No orphan documents found."))
            return

        self.stdout.write(f"\nFound {len(orphans)} orphan document(s).")

        if dry_run:
            self.stdout.write("Dry run — no records deleted.")
            return

        orphan_ids = [doc.id for doc in orphans]

        # Clear outline references to highlights on these documents
        highlight_ids = set(
            Highlight.objects.filter(document_id__in=orphan_ids).values_list(
                "id", flat=True
            )
        )
        self._clear_outline_references(highlight_ids)

        # Delete highlights, then documents
        Highlight.objects.filter(document_id__in=orphan_ids).delete()
        count = Document.objects.filter(id__in=orphan_ids).delete()[0]

        self.stdout.write(self.style.SUCCESS(f"Deleted {count} record(s)."))
