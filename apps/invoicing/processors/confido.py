"""Confido Legal (formerly Gravity Legal) concrete payment processor.

Confido is a legal-industry payments platform with **native trust vs operating
separation** — the whole reason we can collect both invoice (operating) and
trust/IOLTA deposits through one adapter. Its API is **GraphQL** (not REST like
LawPay, not an SDK like Stripe), and its hosted-fields flow is *inverted*: the
server creates a payment session *first*, hands the client a public session
token, the client's SDK collects + submits the sensitive data to Confido, and
the server then *completes* the session.

Flow (per docs.confidolegal.com):
  1. server:  ``paymentSessionCreate(input:{bankAccountId})`` -> ``paymentSessionToken``
              (a public ``pay_public_*`` token the hosted-fields SDK loads).
              ``bankAccountId`` selects the deposit account and is REQUIRED — pass
              the operating account id for invoices, the trust account id for
              trust deposits. This is where trust vs operating is chosen. (Do NOT
              use ``createPaymentToken`` — Confido deprecated it; it fails on
              emergepay firms in prod. The hosted-fields must be loaded from a
              domain allowlisted under Trusted Domains in the Confido dashboard,
              or the field iframe 400s with "error loading field".)
  2. client:  load ``hosted-fields.js``, ``init({paymentToken})``, user fills the
              iframed fields, ``submitFields()`` sends card/bank data to Confido.
  3. server:  ``paymentSessionComplete(input:{amount, paymentToken, paymentMethod,
              payerEmail})`` -> ``{status, transactions{...}}`` — the actual charge.

So in this adapter ``client_config`` performs step 1 (it hits the API to mint the
session token, unlike the pure ``client_config`` of the other processors), and
``charge`` performs step 3 with the *same* session token the client submitted
against (passed back to us as ``token``). ``bankAccountId`` is baked into the
session at step 1, so ``charge``'s ``trust`` argument is already reflected and
need not be re-applied.

Auth: HTTP header ``x-api-key: <firm secret token>`` (``f_secret_*``). Endpoint:
``https://api.sandbox.gravity-legal.com/v2`` (sandbox) / ``https://api.gravity-legal.com/v2``
(prod).

Transaction status (``status_v2``): ``PENDING`` (authorized, batched, no funds
moved), ``FUNDS_IN_TRANSIT``, ``DEPOSITED`` (settled), ``VOIDED``, ``RETURNED``
(ACH only, post-settlement reversal), ``REFUNDED`` / ``PARTIALLY_REFUNDED``,
``ERROR``. Card ``PENDING`` = funds secured (resolves to SUCCEEDED); ACH
``PENDING`` = still in flight (stays PENDING until DEPOSITED or RETURNED) — so
the reconciliation/return path (see ``pay.reconcile``) is mandatory.

Webhooks are signed: header ``X-SIGNATURE`` = base64( HMAC-SHA512( raw-body,
webhook-secret ) ). We verify that, then re-fetch the transaction for its
authoritative status (the payload carries "typically just an ID").

Schema confirmed against the live sandbox (2026-07-02, GraphQL introspection):
``paymentSessionCreate`` takes ``PaymentSessionCreateInput!`` and REQUIRES
``bankAccountId`` (no auto-default); ``paymentSessionComplete`` takes ``method``
(``PaymentSessionMethod`` enum: ``ACH``/``CREDIT``/``DEBIT``) and
``paymentSessionToken`` (not the ``paymentMethod``/``paymentToken`` names the
public docs imply); ``transaction(id:)`` and ``transactionRefund(transactionId,
amount)`` are as used; ``Transaction`` exposes ``status_v2`` +
``paymentMethod`` (the ``TransactionPaymentMethod`` enum, a bare scalar).

Credit vs debit: Confido validates the session ``method`` against the card's
actual BIN type — completing with ``CREDIT`` for a debit card fails with "card
type is not credit, but CREDIT method was requested" (hit live 2026-08-01). The
hosted-fields client learns the type from its BIN lookup
(``getState().cardData.cardType``) and the pay page forwards it; ``charge``
maps it to ``CREDIT``/``DEBIT`` (via ``metadata["card_type"]``) and, if Confido
still reports a mismatch, retries the completion once with the flipped method.
"""

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal

import requests
from django.conf import settings

from .base import (
    BANK,
    CARD,
    FAILED,
    PENDING,
    REFUNDED,
    RETURNED,
    SUCCEEDED,
    VOIDED,
    ChargeError,
    ChargeResult,
    ClientConfig,
    PaymentProcessor,
    ProcessorConfigError,
    WebhookEvent,
    WebhookVerificationError,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds

# Confido Transaction.status_v2 -> normalized status. PENDING is resolved by
# method in `_normalize` (card PENDING = secured -> SUCCEEDED; ACH PENDING = in
# flight -> PENDING).
_STATUS_MAP = {
    "DEPOSITED": SUCCEEDED,
    "FUNDS_IN_TRANSIT": PENDING,
    "PENDING": PENDING,
    "VOIDED": VOIDED,
    "RETURNED": RETURNED,
    "REFUNDED": REFUNDED,
    "PARTIALLY_REFUNDED": REFUNDED,
    "ERROR": FAILED,
}

# Webhook event type -> the transaction id we care about lives at this JSON path
# in the event's `data`. Reversal events carry the *original* transaction id (the
# one we recorded as processor_txn_id); success/settlement events carry `id`.
_ORIGINAL_ID_EVENTS = frozenset(
    {
        "transaction.refunded",
        "transaction.partially_refunded",
        "transaction.ach_returned",
        "transaction.voided",
    }
)


def _to_cents(amount) -> int:
    """Decimal/float dollars -> integer cents (Confido amount unit)."""
    return int((Decimal(str(amount)) * 100).to_integral_value())


class ConfidoProcessor(PaymentProcessor):
    name = "confido"

    def __init__(
        self,
        *,
        api_key=None,
        api_base=None,
        webhook_secret=None,
        hosted_fields_url=None,
    ):
        self.api_key = api_key if api_key is not None else settings.CONFIDO_API_KEY
        self.api_base = (api_base or settings.CONFIDO_API_BASE).rstrip("/")
        self.webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else settings.CONFIDO_WEBHOOK_SECRET
        )
        self.hosted_fields_url = (
            hosted_fields_url
            if hosted_fields_url is not None
            else settings.CONFIDO_HOSTED_FIELDS_URL
        )
        # Deposit account per destination. BOTH are required (Confido has no
        # auto-default; discover the ids with `bankAccountsList` or the portal).
        # Strip so a whitespace-only .env value (e.g. left by an inline comment)
        # reads as blank rather than a truthy garbage id.
        self.operating_bank_account_id = (
            settings.CONFIDO_OPERATING_BANK_ACCOUNT_ID or ""
        ).strip()
        self.trust_bank_account_id = (
            settings.CONFIDO_TRUST_BANK_ACCOUNT_ID or ""
        ).strip()
        if not self.api_key:
            raise ProcessorConfigError("CONFIDO_API_KEY is not configured.")

    def bank_account_id_for(self, *, trust=False):
        """Deposit account id for the destination. Confido requires *exactly one*
        of bankAccountId/paymentLinkId/… on paymentSessionCreate — there is no
        auto-default — so BOTH the operating and trust ids must be configured
        (verified against the sandbox: omitting bankAccountId is a validation
        error)."""
        account_id = (
            self.trust_bank_account_id if trust else self.operating_bank_account_id
        )
        if not account_id:
            which = (
                "CONFIDO_TRUST_BANK_ACCOUNT_ID"
                if trust
                else "CONFIDO_OPERATING_BANK_ACCOUNT_ID"
            )
            raise ProcessorConfigError(f"{which} is not configured.")
        return account_id

    def list_bank_accounts(self) -> list:
        """Read-only: the firm's deposit accounts. Confirms the API key
        authenticates and reveals the operating/trust ids (for pre-flight and
        `manage.py confido_check`)."""
        query = (
            "query { bankAccountsList { bankAccounts "
            "{ id nickname category isDefault isFeeAccount } } }"
        )
        data = self._graphql(query, {}, "List bank accounts")
        return (data.get("bankAccountsList") or {}).get("bankAccounts") or []

    def mint_preflight_session(self, *, trust=False) -> str:
        """Read-only-ish pre-flight: mint a throwaway payment session for the
        given destination account and return its public token. No money moves —
        an uncompleted session just expires. Proves the firm is provisioned to
        accept payments (this is where "No Emergepay Auth Token" would surface)."""
        return self._create_session(trust=trust)

    # --- contract --------------------------------------------------------
    def client_config(self, invoice) -> ClientConfig:
        return self.client_config_for(
            amount_cents=_to_cents(invoice.amount_remaining),
            reference=f"Invoice {invoice.id}",
        )

    def client_config_for(
        self, *, amount_cents, reference, trust=False
    ) -> ClientConfig:
        """Create a Confido payment session and return the public token in
        ``public_key``. The session (and thus its deposit account) is created
        here, at page-render time — see the module docstring on the inverted
        flow."""
        session_token = self._create_session(trust=trust)
        return ClientConfig(
            processor=self.name,
            public_key=session_token,
            amount_cents=amount_cents,
            reference=reference,
            methods=[CARD, BANK],
            hosted_fields_url=self.hosted_fields_url,
            # Confido strongly supports ACH (incl. no-fee trust); offer eCheck.
            echeck=True,
        )

    def charge(
        self,
        *,
        token,
        amount_cents,
        reference,
        method,
        idempotency_key=None,
        metadata=None,
        trust=False,
        client=None,
        matter=None,
    ) -> ChargeResult:
        """Complete the payment session the client submitted against. ``token``
        is the public session token (``paymentSessionToken``) — the deposit
        account was already fixed when the session was created.

        ``client``/``matter`` are optional descriptor dicts (external_id, name,
        email, phone). When present, the paying client and its matter are synced
        into Confido and attached to the transaction — best-effort: a sync
        failure never blocks the charge."""
        # PaymentSessionMethod enum is ACH | CREDIT | DEBIT — and Confido
        # VALIDATES card sessions against the card's actual BIN type ("card type
        # is not credit, but CREDIT method was requested"), so CREDIT-for-all
        # bounces debit cards. The hosted-fields client knows the type after the
        # BIN lookup (getState().cardData.cardType) and passes it up in
        # ``metadata["card_type"]``; default to CREDIT when it's absent and let
        # the mismatch retry below correct us.
        card_type = ((metadata or {}).get("card_type") or "").strip().lower()
        if method == BANK:
            session_method = "ACH"
        else:
            session_method = "DEBIT" if card_type == "debit" else "CREDIT"
        session_input = {
            "amount": int(amount_cents),
            "paymentSessionToken": token,
            "method": session_method,
        }
        payer_email = (metadata or {}).get("payer_email")
        if payer_email:
            session_input["payerEmail"] = payer_email

        # Attach (creating if needed) the client + matter — never blocking.
        client_id, matter_id = self._resolve_client_matter(client, matter)
        if client_id:
            session_input["clientId"] = client_id
        if matter_id:
            session_input["matterId"] = matter_id
        payer_name = (client or {}).get("name")
        if payer_name:
            session_input["payerName"] = payer_name

        query = """
        mutation PaymentSessionComplete($input: PaymentSessionCompleteInput!) {
          paymentSessionComplete(input: $input) {
            status
            transactions { id status_v2 amountProcessed paymentMethod }
          }
        }
        """
        try:
            data = self._graphql(query, {"input": session_input}, "Charge failed")
        except ChargeError as exc:
            flipped = self._flipped_card_method(session_method, exc)
            if not flipped:
                raise
            # A method/BIN mismatch is rejected before any charge is attempted,
            # so the session is still completable — retry once, flipped.
            session_input = {**session_input, "method": flipped}
            data = self._graphql(query, {"input": session_input}, "Charge failed")
        result = data.get("paymentSessionComplete") or {}
        txn = self._first_txn(result)
        if txn is None:
            # No transaction produced -> the session did not result in a charge.
            raise ChargeError(
                result.get("status") or "Charge was not completed.",
                code="not_completed",
                raw=result,
            )
        return self._result(txn, fallback_method=method)

    def fetch_transaction(self, transaction_id) -> ChargeResult:
        query = """
        query Transaction($id: String!) {
          transaction(id: $id) {
            id status_v2 amountProcessed paymentMethod
          }
        }
        """
        data = self._graphql(query, {"id": transaction_id}, "Fetch failed")
        txn = data.get("transaction")
        if not txn:
            raise ChargeError(
                f"Unknown transaction {transaction_id!r}", code="not_found", raw=data
            )
        return self._result(txn)

    def verify_and_parse_webhook(self, request) -> WebhookEvent:
        """Verify Confido's HMAC-SHA512 signature over the raw body, then
        re-fetch the referenced transaction for its authoritative status.

        Confido posts a JSON *array* of ``{data, type, firmId, eventId}``; we act
        on the first event (the reconciler is called once per delivery).
        """
        raw = request.body if isinstance(request.body, bytes) else request.body.encode()
        signature = getattr(request, "signature", "") or ""
        if not self._signature_ok(raw, signature):
            raise WebhookVerificationError("Bad Confido webhook signature.")

        try:
            body = json.loads(raw or b"[]")
        except (ValueError, TypeError) as exc:
            raise WebhookVerificationError(f"Bad webhook body: {exc}") from exc

        event = self._first_event(body)
        if event is None:
            raise WebhookVerificationError("Webhook contained no event.")

        txn_id = self._event_txn_id(event)
        if not txn_id:
            raise WebhookVerificationError("Webhook event has no transaction id.")

        # Re-fetch to confirm — the payload's own status is not trusted.
        confirmed = self.fetch_transaction(txn_id)
        return WebhookEvent(
            processor=self.name,
            event_id=str(event.get("eventId") or ""),
            transaction_id=txn_id,
            status=confirmed.status,
            amount_cents=confirmed.amount_cents,
            raw=event,
            settled=confirmed.settled,
        )

    def refund(
        self, *, transaction_id, amount_cents=None, reference=None
    ) -> ChargeResult:
        refund_input = {"transactionId": transaction_id}
        if amount_cents is not None:
            refund_input["amount"] = int(amount_cents)
        query = """
        mutation TransactionRefund($input: TransactionRefundInput!) {
          transactionRefund(input: $input) {
            transaction { id status_v2 amountProcessed paymentMethod }
          }
        }
        """
        data = self._graphql(query, {"input": refund_input}, "Refund failed")
        txn = (data.get("transactionRefund") or {}).get("transaction")
        if not txn:
            # Fall back to reporting the original transaction's state.
            return self.fetch_transaction(transaction_id)
        return self._result(txn)

    # --- internals -------------------------------------------------------
    def _create_session(self, *, trust=False) -> str:
        # Mint the hosted-fields session token. bankAccountId selects the deposit
        # account (required). Use paymentSessionCreate — NOT createPaymentToken,
        # which Confido has deprecated (it fails on emergepay-backed firms in
        # production with "No Emergepay Auth Token"). The "error loading field"
        # 400 seen with either mutation was a Trusted Domains issue (the parent
        # page's origin must be allowlisted in the Confido dashboard), not the
        # token type. The returned paymentSessionToken is what the hosted-fields
        # SDK loads and what paymentSessionComplete later consumes.
        session_input = {"bankAccountId": self.bank_account_id_for(trust=trust)}
        query = """
        mutation PaymentSessionCreate($input: PaymentSessionCreateInput!) {
          paymentSessionCreate(input: $input) { paymentSessionToken }
        }
        """
        data = self._graphql(
            query, {"input": session_input}, "Could not start payment session"
        )
        token = (data.get("paymentSessionCreate") or {}).get("paymentSessionToken")
        if not token:
            raise ChargeError(
                "Payment session could not be created.", code="session", raw=data
            )
        return token

    # --- client / matter sync (best-effort; never blocks a charge) -------
    @staticmethod
    def _ext(kind, raw):
        """Namespace our record id into a Confido externalId. A bare id (e.g. a
        matter id ``1053``) can collide with another firm's externalId in
        Confido's shared space — the lookup then returns "access denied", which we
        treat as uncertain and skip, so the record never syncs. An app-specific
        prefix keeps ours distinct."""
        return f"kosmos-{kind}-{raw}"

    def _resolve_client_matter(self, client, matter):
        """Return (client_id, matter_id) — either may be None. Syncs the client
        (and its matter under it) into Confido, keyed on our external ids so it's
        idempotent across repeat payments. Any failure yields None rather than
        raising, so a client/matter hiccup can never block the payment."""
        try:
            client_id = self._ensure_client(client)
            matter_id = (
                self._ensure_matter(matter, client_id) if client_id and matter else None
            )
            return client_id, matter_id
        except Exception:  # noqa: BLE001 — attaching is optional; never block.
            logger.warning("Confido client/matter sync failed", exc_info=True)
            return None, None

    def _lookup_external(self, kind, external_id):
        """Look up a client/matter by our external id. Returns (id_or_None,
        definitely_absent) — definitely_absent is True only when Confido reports
        'could not find', so we create only when we're sure it doesn't exist (a
        network/other error must not spawn a duplicate)."""
        query = "query Q($e: String!) { %s(externalId: $e) { id } }" % kind
        try:
            data = self._graphql(query, {"e": external_id}, f"{kind} lookup")
            return (data.get(kind) or {}).get("id"), False
        except ChargeError as exc:
            return None, "could not find" in str(exc).lower()

    def _ensure_client(self, client):
        if not client:
            return None
        raw = (client.get("external_id") or "").strip()
        name = (client.get("name") or "").strip()
        if not raw or not name:
            return None
        external_id = self._ext("client", raw)
        found, absent = self._lookup_external("client", external_id)
        if found:
            return found
        if not absent:
            return None
        add_input = {"clientName": name, "externalId": external_id}
        for src, dest in (("email", "email"), ("phone", "phone")):
            value = (client.get(src) or "").strip()
            if value:
                add_input[dest] = value
        query = (
            "mutation A($input: AddClientInput!) { addClient(input: $input) { id } }"
        )
        data = self._graphql(query, {"input": add_input}, "add client")
        return (data.get("addClient") or {}).get("id")

    def _ensure_matter(self, matter, client_id):
        raw = (matter.get("external_id") or "").strip()
        name = (matter.get("name") or "").strip()
        if not raw or not name:
            return None
        external_id = self._ext("matter", raw)
        found, absent = self._lookup_external("matter", external_id)
        if found:
            return found
        if not absent:
            return None
        # Confido requires matter names to be unique (clients may share a name,
        # matters may not) — a create that collides on name links to the existing
        # matter, which may belong to a different client ("matterId does not match
        # client"). Append our matter id to guarantee a distinct name; placed
        # after the name so Confido's matter list still sorts alphabetically.
        display_name = f"{name} #{raw}"
        add_input = {
            "clientId": client_id,
            "name": display_name,
            "externalId": external_id,
        }
        query = (
            "mutation M($input: MatterCreateInput!) "
            "{ matterCreate(input: $input) { matter { id } } }"
        )
        data = self._graphql(query, {"input": add_input}, "create matter")
        return ((data.get("matterCreate") or {}).get("matter") or {}).get("id")

    def _graphql(self, query, variables, error_prefix) -> dict:
        """POST a GraphQL operation and return its ``data`` object. Raises
        ``ChargeError`` on transport failure or GraphQL/HTTP errors."""
        try:
            resp = requests.post(
                self.api_base,
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ChargeError(
                f"Could not reach payment processor: {exc}", code="network"
            ) from exc

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            message, code = self._first_error(errors)
            raise ChargeError(message or f"{error_prefix}.", code=code, raw=payload)
        if resp.status_code >= 300:
            raise ChargeError(
                f"{error_prefix} (HTTP {resp.status_code}).",
                code=str(resp.status_code),
                raw=payload,
            )
        return payload.get("data") or {}

    def _signature_ok(self, raw_body: bytes, signature: str) -> bool:
        if not self.webhook_secret or not signature:
            return False
        digest = hmac.new(
            self.webhook_secret.encode(), raw_body, hashlib.sha512
        ).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _first_error(errors):
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            err = errors[0]
            code = (err.get("extensions") or {}).get("code")
            return err.get("message"), code
        return None, None

    @staticmethod
    def _flipped_card_method(session_method, exc):
        """If a card completion was rejected because the session method doesn't
        match the card's BIN type ("card type is not credit, but CREDIT method
        was requested"), return the opposite card method to retry with;
        otherwise None. The client-reported type is normally right — this covers
        a missing/stale BIN lookup, and Confido remains the authority."""
        if session_method not in ("CREDIT", "DEBIT"):
            return None
        if "card type is not" not in str(exc).lower():
            return None
        return "DEBIT" if session_method == "CREDIT" else "CREDIT"

    @staticmethod
    def _first_event(body):
        """Confido posts a JSON array of events; tolerate a bare object too."""
        if isinstance(body, list):
            return body[0] if body else None
        if isinstance(body, dict) and ("data" in body or "type" in body):
            return body
        return None

    @staticmethod
    def _event_txn_id(event):
        """The transaction id an event points at. Reversal events name the
        *original* transaction (what we recorded); others carry a plain id."""
        data = event.get("data") or {}
        etype = event.get("type") or ""
        if etype in _ORIGINAL_ID_EVENTS:
            original = data.get("originalTransaction") or {}
            if original.get("id"):
                return original["id"]
        # transaction.* success/settlement events carry {transaction:{id}} or a
        # bare id.
        txn = data.get("transaction")
        if isinstance(txn, dict) and txn.get("id"):
            return txn["id"]
        return data.get("id") or data.get("transactionId")

    def _first_txn(self, session_result):
        txns = session_result.get("transactions") or []
        # Skip refund/void sub-transactions if any; take the first charge.
        return txns[0] if txns else None

    def _result(self, txn, fallback_method=None) -> ChargeResult:
        status, method = self._normalize(txn, fallback_method)
        return ChargeResult(
            processor=self.name,
            transaction_id=str(txn.get("id") or ""),
            status=status,
            amount_cents=int(txn.get("amountProcessed") or 0),
            method=method,
            raw=txn,
            # DEPOSITED is Confido's "in the bank" terminal state (for a card this
            # is its later payout, not the capture the status already reflects).
            settled=(txn.get("status_v2") or "").upper() == "DEPOSITED",
        )

    @staticmethod
    def _normalize(txn, fallback_method=None):
        raw_status = (txn.get("status_v2") or "").upper()
        # Transaction.paymentMethod is the TransactionPaymentMethod enum
        # (ACH/CHECK/CREDIT/DEBIT/…) — a bare scalar, not an object.
        pm = (txn.get("paymentMethod") or "").upper()
        if pm:
            method = BANK if pm in ("ACH", "CHECK") else CARD
        else:
            method = CARD if fallback_method == CARD else (fallback_method or BANK)

        status = _STATUS_MAP.get(raw_status, PENDING)
        # Card funds are secured at PENDING (they'll deposit); treat as settled so
        # the payer sees "paid", not "pending". ACH PENDING stays provisional.
        if status == PENDING and method == CARD:
            status = SUCCEEDED
        return status, method
