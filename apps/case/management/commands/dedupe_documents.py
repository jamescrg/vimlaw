"""Remove duplicate documents that nothing else depends on.

Groups a matter's documents by content fingerprint (same bytes, or same
pages under different PDF metadata; see apps.case.documents.fingerprint)
and, in each group of two or more, deletes the copies that carry no
highlights and are not referenced by a fact, note or email. One copy is
always kept: every referenced copy stays, and when none is referenced the
Drive-synced copy (else the one filed under a proceeding, else the oldest)
is kept. Labels on removed copies move to the kept copy.

Only copies within the same matter are considered: the same filing held
in two matters is each matter's own record, so cross-matter pairs are
reported and left alone.

Dry run by default; pass --apply to delete. Storage files of removed
copies are deleted too (each copy has its own stored file).
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.case.models import Document


class Command(BaseCommand):
    help = (
        "Delete duplicate documents (same matter) that have no highlights or references"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Delete; without it, only report"
        )
        parser.add_argument("--matter", type=int, help="Restrict to one matter id")

    def handle(self, *args, **options):
        docs = (
            Document.objects.exclude(content_hash__isnull=True)
            .select_related("matter")
            .annotate(
                n_highlights=Count("highlights", distinct=True),
                n_facts=Count("facts", distinct=True),
                n_notes=Count("notes", distinct=True),
                n_emails=Count("source_emails", distinct=True),
            )
            .order_by("pk")
        )
        if options["matter"]:
            docs = docs.filter(matter_id=options["matter"])
        docs = list(docs)

        groups = self._group(docs)
        removed = kept_total = 0
        cross_matter = 0
        to_delete = []
        survivors = {}
        for members in groups:
            matters = {d.matter_id for d in members}
            if len(matters) > 1:
                cross_matter += 1
                # Split into per-matter groups; anything spanning matters
                # is reported only.
                by_matter = defaultdict(list)
                for d in members:
                    by_matter[d.matter_id].append(d)
                per_matter = [g for g in by_matter.values() if len(g) > 1]
                self.stdout.write(
                    "Across matters (left alone): "
                    + "; ".join(_label(d) for d in members)
                )
            else:
                per_matter = [members]
            for group in per_matter:
                keep, drop = self._split(group)
                kept_total += len(keep)
                if not drop:
                    continue
                self.stdout.write(
                    f"Matter {group[0].matter_id} ({group[0].matter.name}):"
                )
                for d in keep:
                    self.stdout.write(f"  keep   {_label(d)}  [{_why_kept(d)}]")
                for d in drop:
                    self.stdout.write(f"  remove {_label(d)}")
                    survivors[d.pk] = keep[0]
                to_delete.extend(drop)

        self.stdout.write(
            f"\n{len(to_delete)} duplicate copy(ies) removable in "
            f"{len(groups)} group(s); {cross_matter} group(s) span matters."
        )
        if not options["apply"]:
            self.stdout.write("Dry run; pass --apply to delete.")
            return

        for d in to_delete:
            # Labels on the removed copy move to the kept copy (the only
            # metadata carried over; name, date and category stay as the
            # kept copy has them).
            survivor = survivors.get(d.pk)
            if survivor is not None:
                for label in d.labels.all():
                    survivor.labels.add(label)
            path = d.file.name if d.file else None
            storage = d.file.storage if d.file else None
            d.delete()
            removed += 1
            if path and storage:
                try:
                    storage.delete(path)
                except Exception as exc:
                    self.stderr.write(f"{d.pk}: file {path} not removed: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Removed {removed} duplicate copies."))

    @staticmethod
    def _group(docs):
        """Connected groups: documents linked by either fingerprint."""
        parent = {d.pk: d.pk for d in docs}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        first_by_key = {}
        for d in docs:
            for key in (
                ("hash", d.content_hash),
                ("pages", d.page_fingerprint),
            ):
                if not key[1]:
                    continue
                if key in first_by_key:
                    union(first_by_key[key], d.pk)
                else:
                    first_by_key[key] = d.pk
        members = defaultdict(list)
        for d in docs:
            members[find(d.pk)].append(d)
        return [g for g in members.values() if len(g) > 1]

    @staticmethod
    def _split(group):
        """(keep, remove) for one same-matter group."""
        referenced = [d for d in group if _is_referenced(d)]
        if referenced:
            keep = referenced
        else:
            # Nothing points at any copy: keep the one with the most
            # provenance. Drive-synced first (it would re-sync anyway),
            # then a copy filed under a proceeding (part of the docket),
            # then the oldest.
            drive = [d for d in group if d.drive_file_id]
            docketed = [d for d in group if d.proceeding_id]
            keep = [min(drive or docketed or group, key=lambda d: (d.created_at, d.pk))]
        keep_ids = {d.pk for d in keep}
        return keep, [d for d in group if d.pk not in keep_ids]


def _is_referenced(d):
    return bool(d.n_highlights or d.n_facts or d.n_notes or d.n_emails)


def _why_kept(d):
    reasons = []
    if d.n_highlights:
        reasons.append(f"{d.n_highlights} highlight(s)")
    if d.n_facts:
        reasons.append(f"{d.n_facts} fact(s)")
    if d.n_notes:
        reasons.append(f"{d.n_notes} note(s)")
    if d.n_emails:
        reasons.append(f"{d.n_emails} email(s)")
    if not reasons:
        if d.drive_file_id:
            reasons.append("Drive-synced")
        elif d.proceeding_id:
            reasons.append("filed under a proceeding")
        else:
            reasons.append("oldest copy")
    return ", ".join(reasons)


def _label(d):
    date = f", {d.date}" if d.date else ""
    return f"#{d.pk} {d.name!r} ({d.category}{date})"
