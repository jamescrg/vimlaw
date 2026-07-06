"""Read-only pre-flight for the Confido processor before going live.

Exercises everything short of an actual charge against whatever environment
``CONFIDO_API_BASE`` points at (sandbox or live):

  1. lists the firm's deposit accounts  -> proves the API key authenticates;
  2. checks the configured operating/trust account ids exist in that list;
  3. mints a throwaway payment session for each account -> proves the firm is
     provisioned to accept payments (where "No Emergepay Auth Token" surfaces).

Nothing here charges a card or bank account — an uncompleted session just
expires. Run it after flipping the CONFIDO_* env to live, before the first
penny transaction.
"""

from django.core.management.base import BaseCommand

from apps.invoicing.processors.base import PaymentError
from apps.invoicing.processors.confido import ConfidoProcessor


class Command(BaseCommand):
    help = "Read-only pre-flight check for the Confido processor (no charge)."

    def handle(self, *args, **options):
        try:
            proc = ConfidoProcessor()
        except PaymentError as exc:
            self.stderr.write(self.style.ERROR(f"Config error: {exc}"))
            return

        env = "SANDBOX" if "sandbox" in proc.api_base else "LIVE"
        self.stdout.write(f"Endpoint: {proc.api_base}  [{env}]")
        if env == "SANDBOX":
            self.stdout.write(
                self.style.WARNING(
                    "Still pointed at SANDBOX — drop 'sandbox.' from CONFIDO_API_BASE "
                    "(and CONFIDO_HOSTED_FIELDS_URL) for a live pre-flight."
                )
            )

        ok = True
        ok &= self._check_accounts(proc)
        ok &= self._check_sessions(proc)

        self.stdout.write("")
        if ok:
            self.stdout.write(
                self.style.SUCCESS(
                    "PRE-FLIGHT PASSED — safe to proceed to penny testing."
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR("PRE-FLIGHT FAILED — fix the above before charging.")
            )

    def _check_accounts(self, proc):
        """List accounts (auth) and confirm the configured ids are among them."""
        try:
            accounts = proc.list_bank_accounts()
        except PaymentError as exc:
            self.stdout.write(self.style.ERROR(f"✗ Auth / account list failed: {exc}"))
            return False

        self.stdout.write(
            self.style.SUCCESS(f"✓ Auth OK — {len(accounts)} bank account(s):")
        )
        by_id = {}
        for a in accounts:
            by_id[a.get("id")] = a
            flags = [
                f
                for f, on in (
                    ("default", a.get("isDefault")),
                    ("fee", a.get("isFeeAccount")),
                )
                if on
            ]
            suffix = f" [{', '.join(flags)}]" if flags else ""
            self.stdout.write(
                f"    {(a.get('nickname') or '?')!r:28} id={a.get('id')} "
                f"category={a.get('category') or '?'}{suffix}"
            )

        ok = True
        for label, configured in (
            ("operating", proc.operating_bank_account_id),
            ("trust", proc.trust_bank_account_id),
        ):
            var = f"CONFIDO_{label.upper()}_BANK_ACCOUNT_ID"
            if not configured:
                ok = False
                self.stdout.write(self.style.ERROR(f"    ✗ {var} is not set"))
            elif configured in by_id:
                nickname = by_id[configured].get("nickname")
                self.stdout.write(
                    self.style.SUCCESS(f"    ✓ {label} id matches {nickname!r}")
                )
            else:
                ok = False
                self.stdout.write(
                    self.style.ERROR(
                        f"    ✗ {label} id {configured} not found among this firm's "
                        "accounts (wrong id / wrong environment?)"
                    )
                )
        return ok

    def _check_sessions(self, proc):
        """Mint a throwaway session for each destination account (no charge)."""
        ok = True
        for label, trust in (("operating", False), ("trust", True)):
            try:
                token = proc.mint_preflight_session(trust=trust)
                shown = token[:16] + "…" if len(token) > 16 else token
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ {label} session minted (throwaway, no charge): {shown}"
                    )
                )
            except PaymentError as exc:
                ok = False
                self.stdout.write(
                    self.style.ERROR(f"✗ {label} session mint failed: {exc}")
                )
        return ok
