import difflib

from django.core.management.base import BaseCommand

import apps.mail.google as google
from apps.mail.models import GmailAccount
from apps.matters.models import Matter


class Command(BaseCommand):
    help = (
        "Link Gmail labels to Matter records by setting Matter.gmail_label_name "
        "(the cross-mailbox contract). Interactive; suggests matches by name. "
        "Labels are read from the first connected mailbox."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Only list unlinked Gmail labels; do not prompt.",
        )

    def handle(self, *args, **options):
        if not google.check_credentials():
            self.stderr.write(
                self.style.ERROR(
                    "Gmail is not linked. Connect it at /settings/integrations/."
                )
            )
            return

        labels = google.list_matter_labels(GmailAccount.objects.order_by("id").first())
        if not labels:
            self.stderr.write(
                self.style.ERROR(
                    "No matter labels found in the connected mailbox "
                    "(GMAIL_LABEL_ROOT is "
                    f"{google.settings.GMAIL_LABEL_ROOT!r})."
                )
            )
            return

        linked = {
            m.gmail_label_name
            for m in Matter.objects.exclude(gmail_label_name__isnull=True).exclude(
                gmail_label_name=""
            )
        }
        unmatched = [label for label in labels if label["name"] not in linked]

        if not unmatched:
            self.stdout.write(self.style.SUCCESS("All Gmail labels are linked."))
            return

        if options["list"]:
            self.stdout.write("Unlinked Gmail labels:")
            for label in unmatched:
                self.stdout.write(f"  - {label['short_name']}")
            return

        matters = list(Matter.objects.all().order_by("name"))
        names = [m.name or "" for m in matters]
        linked_now = []

        for label in unmatched:
            self.stdout.write(
                f"\nGmail label: {self.style.WARNING(label['short_name'])}"
            )
            suggestion = difflib.get_close_matches(
                label["short_name"], names, n=1, cutoff=0.4
            )
            suggested = matters[names.index(suggestion[0])] if suggestion else None
            if suggested:
                self.stdout.write(f"  Suggested: [{suggested.id}] {suggested.name}")

            prompt = "  Matter id to link, 'a' to accept suggestion, Enter to skip: "
            answer = input(prompt).strip().lower()

            if not answer:
                continue
            if answer == "a" and suggested:
                matter = suggested
            else:
                matter = (
                    Matter.objects.filter(pk=answer).first()
                    if answer.isdigit()
                    else None
                )
                if not matter:
                    self.stdout.write(self.style.ERROR("  No such matter; skipped."))
                    continue

            if matter.gmail_label_name:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [{matter.id}] {matter.name} is already linked to "
                        f"'{matter.gmail_label_name}'; skipped."
                    )
                )
                continue

            matter.gmail_label_name = label["name"]
            matter.save(update_fields=["gmail_label_name"])
            linked_now.append(matter)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Linked '{label['short_name']}' -> [{matter.id}] {matter.name}"
                )
            )

        # Backfill what's already under the freshly linked labels. The
        # scheduled sync is history-based (it only sees NEW label events),
        # so without this the label's existing messages never arrive - the
        # Emails-tab link button queues the same resync.
        for matter in linked_now:
            self.stdout.write(f"Backfilling {matter.name}...")
            stats = google.resync_matter(matter)
            if stats:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {stats['created']} created, "
                        f"{stats['skipped']} already synced"
                    )
                )
