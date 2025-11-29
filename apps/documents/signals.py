"""Signals for document processing."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.documents.models import Document


@receiver(post_save, sender=Document)
def trigger_ocr_on_upload(sender, instance, created, **kwargs):
    """Queue OCR task when a new PDF document is uploaded."""
    if created:
        file_extension = instance.file.name.split(".")[-1].lower()
        if file_extension == "pdf":
            from django_q.tasks import async_task

            async_task(
                "apps.documents.tasks.process_document_ocr",
                instance.id,
                task_name=f"OCR-{instance.id}",
                group="ocr_processing",
            )
        else:
            # Mark non-PDF files as not applicable for OCR
            Document.objects.filter(id=instance.id).update(ocr_status="not_applicable")
