"""Re-fetch Drive-mirrored documents whose stored file is missing.

Origin: 2026-08-03, prod ran for ~3 hours with STORAGE_BACKEND unset
(PR #482's default is local), so the Drive mirror wrote 25 PDFs to the
web server's local disk instead of the bucket. The rows are fine (OCR ran
against the local copy), the bytes just never reached storage. The
regular sync will not repair them: it compares Drive's modifiedTime to
the row's and treats an unchanged file as done.

This command finds Document rows with a drive_file_id whose file is
absent from storage, downloads the bytes from Drive again, saves them
under the row's existing path, and recomputes the fingerprints. Finished
OCR is kept (same bytes); a document whose OCR is pending or failed is
queued.

Dry run by default; pass --apply to write.
"""

import io

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.case.models import Document
from apps.drive import google
from apps.drive.records import _queue_ocr


class Command(BaseCommand):
    help = "Re-download Drive-mirrored documents whose file is missing from storage"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the restored files (default: report only)",
        )
        parser.add_argument(
            "--ids",
            nargs="*",
            type=int,
            help="Restrict to these document ids",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        queryset = (
            Document.objects.exclude(drive_file_id__isnull=True)
            .exclude(drive_file_id="")
            .exclude(file="")
            .order_by("id")
        )
        if options["ids"]:
            queryset = queryset.filter(id__in=options["ids"])

        missing = []
        for doc in queryset.iterator():
            try:
                present = doc.file.storage.exists(doc.file.name)
            except Exception as exc:
                raise CommandError(f"Storage check failed for {doc.id}: {exc}")
            if not present:
                missing.append(doc)
                self.stdout.write(
                    f"  MISSING  {doc.id:>5}  matter {doc.matter_id}  "
                    f"{doc.file.name}  drive {doc.drive_file_id}"
                )

        if not missing:
            self.stdout.write(self.style.SUCCESS("Every Drive document is in storage."))
            return
        self.stdout.write(f"\n{len(missing)} document(s) missing from storage.")
        if not apply:
            self.stdout.write("Dry run: pass --apply to re-fetch them from Drive.")
            return

        service = google.build_service()
        if not service:
            raise CommandError("Drive is not linked; cannot download.")

        restored = failed = 0
        for doc in missing:
            try:
                content = google._download(
                    service, {"id": doc.drive_file_id, "mimeType": "application/pdf"}
                )
                # Same basename the mirror uses; the path is the row's own.
                doc.file.save(f"{doc.pk}.pdf", ContentFile(content), save=False)
                doc.set_fingerprints(io.BytesIO(content), size=len(content))
                doc.save(update_fields=["file", "content_hash", "page_fingerprint"])
                if not doc.file.storage.exists(doc.file.name):
                    raise RuntimeError("file did not land in storage")
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  FAILED   {doc.id:>5}  {exc}"))
                continue
            restored += 1
            self.stdout.write(
                f"  RESTORED {doc.id:>5}  {doc.file.name}  {len(content):,} bytes"
            )
            # extracted / completed / not_applicable are finished states
            # and the bytes are the ones that OCR already read.
            if doc.ocr_status in ("pending", "failed"):
                _queue_ocr(doc.pk)
                self.stdout.write(f"           {doc.id:>5}  OCR queued")

        style = self.style.SUCCESS if not failed else self.style.WARNING
        self.stdout.write(style(f"\nRestored {restored}, failed {failed}."))
