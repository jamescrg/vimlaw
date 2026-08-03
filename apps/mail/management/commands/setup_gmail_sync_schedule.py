from django.core.management.base import BaseCommand

from apps.management.schedules import install_schedules


class Command(BaseCommand):
    help = (
        "Create or update the Gmail sync schedules: an incremental history "
        "sync every 2 minutes and a weekly full re-list (early Monday) to "
        "reconcile drift the history feed can't repair. No env gate: the "
        "sync is read-only and no-ops when no Gmail account is connected, so "
        "dev inheriting these rows via the nightly prod-to-dev "
        "copy is harmless."
    )

    def handle(self, *args, **options):
        names = {"gmail-sync", "gmail-sync-weekly-full"}
        for spec, created in install_schedules(names=names):
            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{action} {spec.name} (cron: {spec.cron})")
            )
