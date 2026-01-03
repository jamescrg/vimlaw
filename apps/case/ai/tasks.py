"""
Background tasks for AI chat processing.
"""

import logging
import os
import tempfile
import time
from io import BytesIO

from django.core.cache import cache
from django.core.files.storage import default_storage
from pypdf import PdfReader

from .anthropic_client import send_to_claude
from .citations import citations_to_dict, verify_all_citations
from .gemini_client import send_to_gemini_streaming

logger = logging.getLogger(__name__)


def process_ai_request(
    conversation_id: int,
    context_text: str,
    chat_history: list[dict],
    llm: str,
):
    """
    Process AI request in background thread, updating status along the way.

    Args:
        conversation_id: ID of the conversation being processed
        context_text: The assembled matter context
        chat_history: List of message dicts with role, content, and optionally user_name
        llm: The LLM to use (claude, gemini-flash, gemini-pro)
    """
    cache_key = f"ai_status_{conversation_id}"
    started_at = time.time()

    # Check if there are multiple participants and format messages accordingly
    user_names = {msg.get("user_name") for msg in chat_history if msg.get("user_name")}
    if len(user_names) > 1:
        # Multiple participants - prepend names to user messages
        for msg in chat_history:
            if msg["role"] == "user" and msg.get("user_name"):
                msg["content"] = f"[{msg['user_name']}]: {msg['content']}"

    def update_status(status: str, message: str):
        """Update the cache with current status."""
        cache.set(
            cache_key,
            {
                "status": status,
                "message": message,
                "started_at": started_at,
            },
            timeout=600,
        )

    try:
        # Set connecting status
        update_status("connecting", "Connecting to AI...")

        # Brief pause to show connecting status
        time.sleep(0.3)

        if llm in ("gemini-flash", "gemini-pro", "gemini-3-pro"):
            # Use streaming with thought summaries for Gemini
            model_map = {
                "gemini-flash": "gemini-2.5-flash",
                "gemini-pro": "gemini-2.5-pro",
                "gemini-3-pro": "gemini-3-pro-preview",
            }
            model = model_map[llm]

            update_status("thinking", "Thinking...")

            def on_thought(thought_text: str):
                """Callback for thought summaries from Gemini."""
                # Truncate long thoughts for display
                display_text = thought_text[:100]
                if len(thought_text) > 100:
                    display_text += "..."
                update_status("thinking", display_text)

            response_text, input_tokens, output_tokens = send_to_gemini_streaming(
                context_text, chat_history, model=model, on_thought=on_thought
            )
        else:
            # Claude - show elapsed time updates
            update_status("generating", "Generating response...")

            response_text, input_tokens, output_tokens = send_to_claude(
                context_text, chat_history
            )

        # Verify citations in the response
        update_status("verifying", "Verifying citations...")
        logger.info(
            "Starting citation verification for conversation %s", conversation_id
        )
        try:
            verified_citations = verify_all_citations(response_text)
            citations_data = citations_to_dict(verified_citations)
            logger.info(
                "Citation verification complete for conversation %s: %d citations found",
                conversation_id,
                len(citations_data),
            )
        except Exception as e:
            logger.exception(
                "Citation verification failed for conversation %s: %s",
                conversation_id,
                e,
            )
            citations_data = []

        # Set complete status with response data
        logger.info(
            "Storing %d citations in cache for conversation %s",
            len(citations_data),
            conversation_id,
        )
        cache.set(
            cache_key,
            {
                "status": "complete",
                "message": "Complete",
                "response": response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "citations": citations_data,
            },
            timeout=600,
        )

    except Exception as e:
        logger.exception(
            "Error in background AI request for conversation %s", conversation_id
        )
        cache.set(
            cache_key,
            {
                "status": "error",
                "message": f"Error: {str(e)}",
            },
            timeout=600,
        )


# Minimum characters to consider a PDF as having a sufficient text layer
TEXT_THRESHOLD = 500


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


def run_ocrmypdf_simple(input_content):
    """
    Run ocrmypdf on PDF content to create a searchable PDF.

    Args:
        input_content: bytes of the original PDF

    Returns:
        bytes of the OCR'd PDF with embedded text layer
    """
    import ocrmypdf

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
            force_ocr=True,
            deskew=True,
            optimize=1,
            output_type="pdf",
        )

        with open(output_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(input_path)
        os.unlink(output_path)


def process_chat_attachment_ocr(attachment_id):
    """
    Background task to process a chat attachment PDF for text extraction/OCR.

    Args:
        attachment_id: ID of the ChatAttachment to process
    """
    from .models import ChatAttachment

    try:
        attachment = ChatAttachment.objects.get(id=attachment_id)
    except ChatAttachment.DoesNotExist:
        logger.error(f"ChatAttachment {attachment_id} not found for OCR processing")
        return

    # Check if file is a PDF
    file_extension = attachment.filename.split(".")[-1].lower()
    if file_extension != "pdf":
        attachment.ocr_status = "failed"
        attachment.ocr_text = "(Not a PDF file)"
        attachment.save(update_fields=["ocr_status", "ocr_text"])
        return

    # Update status to processing
    attachment.ocr_status = "processing"
    attachment.save(update_fields=["ocr_status"])

    try:
        # Read file from storage
        with default_storage.open(attachment.file.name, "rb") as f:
            original_content = f.read()

        # Try to extract text from existing text layer
        existing_text, page_count = extract_existing_text(original_content)

        if len(existing_text.strip()) > TEXT_THRESHOLD:
            # PDF already has a good text layer - just store the text
            logger.info(
                f"ChatAttachment {attachment_id} has existing text layer "
                f"({len(existing_text)} chars), skipping OCR"
            )
            attachment.ocr_text = existing_text
            attachment.ocr_status = "completed"
            attachment.save(update_fields=["ocr_text", "ocr_status"])
        else:
            # Need to OCR
            logger.info(
                f"ChatAttachment {attachment_id} needs OCR "
                f"(only {len(existing_text.strip())} chars found)"
            )

            ocr_pdf_content = run_ocrmypdf_simple(original_content)

            # Extract text from the OCR'd PDF
            final_text, _ = extract_existing_text(ocr_pdf_content)

            attachment.ocr_text = final_text
            attachment.ocr_status = "completed"
            attachment.save(update_fields=["ocr_text", "ocr_status"])

            logger.info(
                f"OCR completed for ChatAttachment {attachment_id}: "
                f"{len(final_text)} chars"
            )

    except Exception as e:
        logger.exception(f"OCR failed for ChatAttachment {attachment_id}")
        attachment.ocr_status = "failed"
        attachment.ocr_text = f"(OCR failed: {str(e)})"
        attachment.save(update_fields=["ocr_status", "ocr_text"])
