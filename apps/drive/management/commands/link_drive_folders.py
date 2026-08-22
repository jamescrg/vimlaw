import difflib

from django.core.management.base import BaseCommand

import apps.drive.google as google
from apps.matters.models import Matter


class Command(BaseCommand):
    help = (
        "Link Google Drive matter folders (under the Drive root) to Matter "
        "records (Matter.drive_folder + drive_folder_id). Interactive; suggests "
        "matches by name. Subfolder mapping happens in the Documents tab."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Only list unmatched Drive folders; do not prompt.",
        )

    def handle(self, *args, **options):
        if not google.check_credentials():
            self.stderr.write(
                self.style.ERROR(
                    "Google Drive is not linked. Connect it at /settings/integrations/."
                )
            )
            return

        service = google.build_service()
        root_id = google._find_root_folder(service)
        if not root_id:
            self.stderr.write(
                self.style.ERROR(
                    f"Drive root folder '{google.settings.DRIVE_NOTES_ROOT}' not found."
                )
            )
            return

        drive_folders = google.list_child_folders(service, root_id)
        linked_ids = set(
            Matter.objects.exclude(drive_folder_id__isnull=True).values_list(
                "drive_folder_id", flat=True
            )
        )
        linked_names = {
            m.drive_folder
            for m in Matter.objects.exclude(drive_folder__isnull=True).exclude(
                drive_folder=""
            )
        }
        unmatched = [
            f
            for f in drive_folders
            if f["id"] not in linked_ids and f["name"] not in linked_names
        ]

        if not unmatched:
            self.stdout.write(
                self.style.SUCCESS("All Drive matter folders are linked.")
            )
            return

        if options["list"]:
            self.stdout.write("Unmatched Drive folders:")
            for f in unmatched:
                self.stdout.write(f"  - {f['name']}")
            return

        matters = list(Matter.objects.all().order_by("name"))
        names = [m.name or "" for m in matters]

        for entry in unmatched:
            folder = entry["name"]
            self.stdout.write(f"\nDrive folder: {self.style.WARNING(folder)}")
            suggestion = difflib.get_close_matches(folder, names, n=1, cutoff=0.4)
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

            matter.drive_folder = folder
            matter.drive_folder_id = entry["id"]
            matter.save(update_fields=["drive_folder", "drive_folder_id"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Linked '{folder}' -> [{matter.id}] {matter.name}"
                )
            )
