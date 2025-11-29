"""Background tasks for document processing."""

import logging
import os
import tempfile
from io import BytesIO

import ocrmypdf
from django.contrib.postgres.search import SearchVector
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from ocrmypdf import hookimpl
from pypdf import PdfReader

from apps.documents.ocr_progress import DatabaseProgressBar

logger = logging.getLogger(__name__)

# Minimum characters to consider a PDF as having a sufficient text layer
TEXT_THRESHOLD = 500

# Store document_id for the progress bar to access (set before calling ocrmypdf)
_current_document_id = None


@hookimpl
def get_progressbar_class():
    """Return a progress bar class bound to the current document."""

    class BoundProgressBar(DatabaseProgressBar):
        def __init__(self, **kwargs):
            super().__init__(document_id=_current_document_id, **kwargs)

    return BoundProgressBar


def extract_existing_text(pdf_content):
    """
    Extract text from existing PDF text layer using pypdf.

    Args:
        pdf_content: bytes of the PDF file

    Returns:
        tuple: (extracted_text, page_count)
    """
    reader = PdfReader(BytesIO(pdf_content))
    text_parts = []

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text_parts.append(f"--- Page {page_num} ---\n{text}")

    return "\n\n".join(text_parts), len(reader.pages)


def has_sufficient_text(text, threshold=TEXT_THRESHOLD):
    """Check if extracted text meets minimum threshold."""
    return len(text.strip()) > threshold


def run_ocrmypdf(input_content, document_id=None):
    """
    Run ocrmypdf on PDF content to create a searchable PDF.

    Args:
        input_content: bytes of the original PDF
        document_id: optional document ID for progress tracking

    Returns:
        bytes of the OCR'd PDF with embedded text layer
    """
    global _current_document_id
    _current_document_id = document_id

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as input_file:
        input_file.write(input_content)
        input_path = input_file.name

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output_file:
        output_path = output_file.name

    try:
        ocrmypdf.ocr(
            input_path,
            output_path,
            language=["eng"],
            force_ocr=True,  # Force OCR even if text layer appears to exist
            deskew=True,
            optimize=1,
            output_type="pdf",
            plugins=[__name__],  # Register this module as plugin for progress tracking
            progress_bar=True,  # Enable progress bar
        )

        with open(output_path, "rb") as f:
            return f.read()
    finally:
        _current_document_id = None
        os.unlink(input_path)
        os.unlink(output_path)


def process_document_ocr(document_id):
    """
    Background task to process a PDF document for text extraction/OCR.

    Flow:
    1. Check if PDF has existing text layer (>500 chars)
    2. If yes: extract text, store in database, set status to "extracted"
    3. If no: run ocrmypdf to create searchable PDF, replace original file,
       set status to "completed"
    """
    from apps.documents.models import Document

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"Document {document_id} not found for OCR processing")
        return

    # Check if file is a PDF
    file_extension = document.file.name.split(".")[-1].lower()
    if file_extension != "pdf":
        document.ocr_status = "not_applicable"
        document.save(update_fields=["ocr_status"])
        return

    # Update status to processing
    document.ocr_status = "processing"
    document.save(update_fields=["ocr_status"])

    try:
        # Download file from storage (S3/DigitalOcean Spaces)
        with default_storage.open(document.file.name, "rb") as f:
            original_content = f.read()

        # Try to extract text from existing text layer
        existing_text, page_count = extract_existing_text(original_content)

        if has_sufficient_text(existing_text):
            # PDF already has a good text layer - just store the text
            logger.info(
                f"Document {document_id} has existing text layer "
                f"({len(existing_text)} chars), skipping OCR"
            )

            document.ocr_text = existing_text
            document.page_count = page_count
            document.ocr_status = "extracted"
            document.ocr_processed_at = timezone.now()
            document.ocr_error = None
            document.save(
                update_fields=[
                    "ocr_text",
                    "ocr_status",
                    "ocr_processed_at",
                    "ocr_error",
                    "page_count",
                ]
            )
        else:
            # Need to OCR - run ocrmypdf to create searchable PDF
            logger.info(
                f"Document {document_id} needs OCR "
                f"(only {len(existing_text.strip())} chars found)"
            )

            # Set page_count early so progress can show "X/Y"
            document.page_count = page_count
            document.ocr_pages_done = 0
            document.save(update_fields=["page_count", "ocr_pages_done"])

            ocr_pdf_content = run_ocrmypdf(original_content, document_id=document_id)

            # Replace original file with OCR'd version
            file_path = document.file.name
            default_storage.delete(file_path)
            default_storage.save(file_path, ContentFile(ocr_pdf_content))

            # Extract text from the new OCR'd PDF
            final_text, page_count = extract_existing_text(ocr_pdf_content)

            document.ocr_text = final_text
            document.page_count = page_count
            document.ocr_status = "completed"
            document.ocr_processed_at = timezone.now()
            document.ocr_error = None
            document.save(
                update_fields=[
                    "ocr_text",
                    "ocr_status",
                    "ocr_processed_at",
                    "ocr_error",
                    "page_count",
                ]
            )

            logger.info(
                f"OCR completed for document {document_id}: {len(final_text)} chars"
            )

        # Update search vector
        Document.objects.filter(id=document_id).update(
            search_vector=SearchVector("name", "description", "ocr_text")
        )

    except Exception as e:
        logger.exception(f"OCR failed for document {document_id}")
        document.ocr_status = "failed"
        document.ocr_error = str(e)
        document.save(update_fields=["ocr_status", "ocr_error"])


def retry_failed_ocr(document_id):
    """Retry OCR for a failed document."""
    from apps.documents.models import Document

    document = Document.objects.get(id=document_id)
    document.ocr_status = "pending"
    document.ocr_error = None
    document.save(update_fields=["ocr_status", "ocr_error"])

    process_document_ocr(document_id)
