from django.core.management.base import BaseCommand, CommandError

import apps.mail.google as google
from apps.accounts.models import CustomUser
from apps.mail.models import Email, GmailAccount, GmailSyncState


class Command(BaseCommand):
    help = (
        "One-time multi-account migration: turn the legacy shared token file "
        "(GOOGLE_DATA_DIR/email_tokens.json) into the given user's GmailAccount, move "
        "the sync cursor onto it, claim all existing Email rows, and backfill "
        "Email.message_id (the cross-mailbox dedupe key) from Gmail. Run "
        "BEFORE anyone else connects a mailbox."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="The user who owns the original mailbox.")
        parser.add_argument(
            "--skip-backfill",
            action="store_true",
            help="Skip the Message-ID backfill fetches (rerun later; dedupe "
            "against other mailboxes only works for backfilled rows).",
        )

    def handle(self, *args, **options):
        user = CustomUser.objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError(f"No user named {options['username']!r}.")

        account = GmailAccount.objects.filter(user=user).first()
        if account is None:
            try:
                with open(google.GMAIL_TOKEN_PATH, "r") as f:
                    token = f.read()
            except FileNotFoundError:
                token = ""
            if "token" not in token:
                raise CommandError(
                    "No legacy token file and no existing GmailAccount; "
                    "connect Gmail on the integrations page instead."
                )
            account = GmailAccount(user=user, token=token)

        service = google.build_service(account)
        if not service:
            raise CommandError("Could not build a Gmail service from the token.")
        profile = service.users().getProfile(userId="me").execute()
        account.address = profile.get("emailAddress", account.address or "")

        # Carry the incremental cursor over so adoption doesn't force a
        # re-bootstrap of the whole mailbox.
        state = GmailSyncState.objects.first()
        if state and state.history_id and not account.history_id:
            account.history_id = state.history_id
        account.save()
        self.stdout.write(
            self.style.SUCCESS(f"Account: {account.address} -> {user.username}")
        )

        claimed = Email.objects.filter(account__isnull=True).update(account=account)
        self.stdout.write(self.style.SUCCESS(f"Claimed {claimed} existing emails."))

        if options["skip_backfill"]:
            return

        # Message-ID backfill: metadata-only fetches (headers, no bodies).
        updated = failed = 0
        rows = Email.objects.filter(account=account, message_id="")
        for email in rows.iterator():
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=email.gmail_id,
                        format="metadata",
                        metadataHeaders=["Message-ID"],
                    )
                    .execute()
                )
            except Exception:
                failed += 1
                continue
            headers = msg.get("payload", {}).get("headers", [])
            value = next(
                (
                    h.get("value", "")
                    for h in headers
                    if h.get("name", "").lower() == "message-id"
                ),
                "",
            )
            if value:
                # Queryset update: keep updated_at honest for the
                # auto-summary's since= filtering (rows are "immutable").
                Email.objects.filter(pk=email.pk).update(message_id=value.strip()[:998])
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Message-ID backfill: {updated} updated, {failed} fetch failures."
            )
        )
