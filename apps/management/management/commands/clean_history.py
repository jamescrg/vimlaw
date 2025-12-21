"""Management command to clean up old history records."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete history records older than specified days (default: 90)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Delete history older than this many days (default: 90)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        self.stdout.write(
            f"Cleaning history older than {days} days (before {cutoff.date()})"
        )
        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - no records will be deleted")
            )

        # Find all history tables
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename LIKE '%historical%'
                ORDER BY tablename
            """
            )
            history_tables = [row[0] for row in cursor.fetchall()]

        total_deleted = 0

        for table in history_tables:
            with connection.cursor() as cursor:
                # Count records to delete
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE history_date < %s",
                    [cutoff],
                )
                count = cursor.fetchone()[0]

                if count > 0:
                    if dry_run:
                        self.stdout.write(
                            f"  {table}: {count:,} records would be deleted"
                        )
                    else:
                        cursor.execute(
                            f"DELETE FROM {table} WHERE history_date < %s",
                            [cutoff],
                        )
                        self.stdout.write(f"  {table}: {count:,} records deleted")
                    total_deleted += count

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nTotal: {total_deleted:,} records would be deleted"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nTotal: {total_deleted:,} records deleted")
            )
