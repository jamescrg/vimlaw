from django.core.management.base import BaseCommand

from apps.management.schedules import install_schedules


class Command(BaseCommand):
    help = (
        "Create or update the weekly chat-purge schedule (Sunday 03:00 "
        "local): deletes AI chat history for matters closed past the "
        "retention window. Run once on prod after deploy (same pattern as "
        "setup_auto_summary_schedule)."
    )

    def handle(self, *args, **options):
        spec, created = install_schedules(names={"chat-purge-weekly"})[0]
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} {spec.name} ({spec.cron})"))
