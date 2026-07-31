from django.core.management.base import BaseCommand

import apps.mail.google as google
from apps.mail.models import Email
from apps.mail.parser import parse_payload


class Command(BaseCommand):
    help = (
        "Refetch synced emails that have no stored HTML body (one-off "
        "backfill after the body_html field was added). Rows whose message "
        "genuinely has no HTML part are refetched each run; use --matter to "
        "limit scope."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--matter", type=int, default=None, help="Limit to one matter id."
        )

    def handle(self, *args, **options):
        if not google.check_credentials():
            self.stderr.write(self.style.ERROR("Gmail is not linked."))
            return

        service = google.build_service()
        emails = Email.objects.filter(body_html="")
        if options["matter"]:
            emails = emails.filter(matter_id=options["matter"])

        updated = skipped = failed = 0
        for email in emails.iterator():
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=email.gmail_id, format="full")
                    .execute()
                )
            except Exception:
                failed += 1
                continue
            parsed = parse_payload(msg)
            if parsed.body_html:
                email.body_html = parsed.body_html
                email.save(update_fields=["body_html"])
                updated += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete: {updated} updated, "
                f"{skipped} without HTML part, {failed} fetch failures."
            )
        )
