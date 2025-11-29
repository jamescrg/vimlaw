"""Management command to update search vectors for documents and highlights."""

from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand

from apps.documents.models import Document, Highlight


class Command(BaseCommand):
    help = "Update search vectors for all documents and highlights"

    def handle(self, *args, **options):
        # Update document search vectors
        doc_count = Document.objects.update(
            search_vector=SearchVector("name", "description", "ocr_text")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Updated {doc_count} document search vectors")
        )

        # Update highlight search vectors
        highlight_count = Highlight.objects.update(
            search_vector=SearchVector("slug", "text")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Updated {highlight_count} highlight search vectors")
        )
