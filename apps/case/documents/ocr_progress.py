"""Custom progress bar for ocrmypdf that updates the database."""


class DatabaseProgressBar:
    """Custom progress bar that updates Document.ocr_pages_done during OCR."""

    def __init__(
        self,
        *,
        total=None,
        desc=None,
        unit=None,
        disable=False,
        document_id=None,
        **kwargs,
    ):
        self.total = total
        self.desc = desc
        self.unit = unit
        self.document_id = document_id
        self.current = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, n=1, *, completed=None):
        if completed is not None:
            self.current = completed
        else:
            self.current += n

        # Only update DB during "OCR" step with page units
        if self.document_id and self.unit == "page" and self.desc == "OCR":
            from apps.case.models import Document

            Document.objects.filter(id=self.document_id).update(
                ocr_pages_done=int(self.current)
            )
