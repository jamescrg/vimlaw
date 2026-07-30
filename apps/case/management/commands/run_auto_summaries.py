from django.core.management.base import BaseCommand, CommandError

from apps.case.ai.auto_summary import refresh_auto_summaries
from apps.matters.models import Matter


class Command(BaseCommand):
    help = (
        "Queue auto-summary and auto-agenda refreshes on demand (any "
        "environment; qcluster must be running to process them)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Rebuild from the full record instead of incrementally",
        )
        parser.add_argument(
            "--matter",
            type=int,
            help="Refresh a single matter id instead of all open matters",
        )

    def handle(self, *args, **options):
        if options["matter"]:
            from django_q.tasks import async_task

            matter_id = options["matter"]
            if not Matter.objects.filter(id=matter_id).exists():
                raise CommandError(f"Matter {matter_id} does not exist")
            async_task(
                "apps.case.ai.auto_summary.refresh_matter_auto_summary",
                matter_id,
                options["full"],
                task_name=f"AutoSummary-{matter_id}",
                group="auto_summary",
            )
            queued = 1
        else:
            queued = refresh_auto_summaries(force_full=options["full"])

        mode = "full rebuild" if options["full"] else "incremental refresh"
        self.stdout.write(self.style.SUCCESS(f"Queued {mode} for {queued} matter(s)"))
