"""Management command to queue OCR for existing PDF documents."""

from django.core.management.base import BaseCommand
from django_q.tasks import async_task

from apps.case.models import Document


class Command(BaseCommand):
    help = "Queue OCR processing for all existing PDF documents that have not been processed"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-process all PDFs, including already completed ones",
        )

    def handle(self, *args, **options):
        reprocess_all = options.get("all", False)

        # Find PDFs that need OCR
        pdfs = Document.objects.filter(file__endswith=".pdf")

        if not reprocess_all:
            pdfs = pdfs.filter(ocr_status__in=["pending", "failed"])

        count = 0
        for doc in pdfs:
            async_task(
                "apps.case.documents.tasks.process_document_ocr",
                doc.id,
                task_name=f"OCR-Backfill-{doc.id}",
                group="ocr_processing",
            )
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Queued {count} documents for OCR processing")
        )
