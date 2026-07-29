"""Missed-webhook backstop: poll the processor for every in-flight online
payment row and settle, confirm, or reverse it.

Settlement is normally webhook-driven (`/webhooks/<processor>/` →
`pay.reconcile`), but a delivery that never arrives leaves an ACH payment
`pending` (and a trust deposit unconfirmed) forever. This command re-fetches
each such transaction from the processor's API and applies the result through
the same reconciliation rules. Idempotent; safe to run on a schedule.
"""

from django.core.management.base import BaseCommand

from apps.invoicing.pay.reconcile import poll_pending


class Command(BaseCommand):
    help = (
        "Poll the processor for in-flight online payments and trust deposits "
        "and settle, confirm, or reverse them (missed-webhook backstop)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without applying anything.",
        )

    def handle(self, *args, **options):
        lines = poll_pending(dry_run=options["dry_run"])
        if not lines:
            self.stdout.write("Nothing to reconcile.")
            return
        for line in lines:
            self.stdout.write(line)
