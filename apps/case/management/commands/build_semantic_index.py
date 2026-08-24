"""Backfill the semantic material index (apps/case/ai/semantic.py).

Embeds every open matter's documents, notes, emails, highlights and
timeline facts, plus the firm library. Unchanged objects (same content
hash) are skipped, so re-runs are cheap; run once after deploy and
whenever the index needs a catch-up (for example after qcluster
downtime).
"""

from django.core.management.base import BaseCommand

from apps.case.ai.semantic import index_object
from apps.case.models import Document, Fact, Highlight
from apps.mail.models import Email
from apps.matters.models import Matter
from apps.notes.models import Note, get_library_notes


class Command(BaseCommand):
    help = "Embed matter materials for semantic search"

    def add_arguments(self, parser):
        parser.add_argument("--matter", type=int, help="One matter id only")
        parser.add_argument("--library", action="store_true", help="Library notes only")

    def handle(self, *args, **options):
        totals = {"objects": 0, "chunks": 0}

        def run(kind, queryset):
            for obj in queryset.iterator():
                chunks = index_object(kind, obj)
                totals["objects"] += 1
                totals["chunks"] += chunks

        if not options["library"]:
            matters = Matter.objects.filter(status="Open")
            if options["matter"]:
                matters = Matter.objects.filter(id=options["matter"])
            for matter in matters:
                self.stdout.write(f"Indexing {matter.name} ({matter.id})...")
                run("document", Document.objects.filter(matter=matter))
                run("note", Note.objects.filter(matter=matter))
                run("email", Email.objects.filter(matter=matter).dedup())
                run(
                    "highlight",
                    Highlight.objects.filter(document__matter=matter).select_related(
                        "document", "caselaw"
                    ),
                )
                run(
                    "highlight",
                    Highlight.objects.filter(caselaw__matter=matter).select_related(
                        "document", "caselaw"
                    ),
                )
                run("fact", Fact.objects.filter(matter=matter))

        if not options["matter"]:
            self.stdout.write("Indexing the firm library...")
            run("library", get_library_notes())

        self.stdout.write(
            self.style.SUCCESS(
                f"Indexed {totals['objects']} objects, {totals['chunks']} chunks "
                "written (unchanged objects skipped)."
            )
        )
