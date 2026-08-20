"""Backfill duplicate-detection fingerprints on existing documents.

Reads each document's file from storage once and stores its content hash
and (for PDFs) page fingerprint, then reports the duplicate groups already
present. Run after deploying the fingerprint fields; new uploads are
fingerprinted as they arrive.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.case.models import Document


class Command(BaseCommand):
    help = "Compute content fingerprints for documents that lack them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true", help="Recompute every document"
        )

    def handle(self, *args, **options):
        docs = Document.objects.exclude(file="").order_by("pk")
        if not options["all"]:
            docs = docs.filter(content_hash__isnull=True)

        done = failed = 0
        for doc in docs.iterator():
            try:
                doc.file.open("rb")
                doc.set_fingerprints(doc.file, size=doc.file.size)
                doc.file.close()
            except Exception as exc:
                failed += 1
                self.stderr.write(f"{doc.pk}: {exc}")
                continue
            Document.objects.filter(pk=doc.pk).update(
                content_hash=doc.content_hash, page_fingerprint=doc.page_fingerprint
            )
            done += 1
            if done % 50 == 0:
                self.stdout.write(f"{done} fingerprinted...")

        self.stdout.write(
            self.style.SUCCESS(f"Fingerprinted {done} documents ({failed} failed)")
        )

        groups = defaultdict(list)
        for pk, matter_id, name, chash, pfp in Document.objects.exclude(
            content_hash__isnull=True
        ).values_list("pk", "matter_id", "name", "content_hash", "page_fingerprint"):
            groups[chash].append((pk, matter_id, name))
            if pfp and pfp != chash:
                groups[f"pages:{pfp}"].append((pk, matter_id, name))
        seen = set()
        dup_groups = 0
        for members in groups.values():
            key = tuple(sorted(m[0] for m in members))
            if len(members) < 2 or key in seen:
                continue
            seen.add(key)
            dup_groups += 1
            self.stdout.write(
                "Duplicates: "
                + "; ".join(
                    f"#{pk} {name!r} (matter {mid})" for pk, mid, name in members
                )
            )
        self.stdout.write(f"{dup_groups} duplicate group(s) in the system")
