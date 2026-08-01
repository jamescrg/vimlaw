from django.core.management.base import BaseCommand

from apps.case.ai.purge import DEFAULT_RETENTION_DAYS, purge_closed_chats


class Command(BaseCommand):
    help = (
        "Delete AI chat history (conversations, messages and their history "
        "rows) for matters closed longer than the retention window. Chats "
        "are working notes with no lasting value once a matter closes; the "
        "client file lives in Drive and Gmail. Scheduled weekly via "
        "setup_chat_purge_schedule."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_RETENTION_DAYS,
            help=f"Retention window after closing (default {DEFAULT_RETENTION_DAYS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting.",
        )

    def handle(self, *args, **options):
        stats = purge_closed_chats(days=options["days"], dry_run=options["dry_run"])
        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Purged {stats['conversations']} conversation(s) and "
                f"{stats['messages']} message(s) across {stats['matters']} "
                f"closed matter(s)."
            )
        )
