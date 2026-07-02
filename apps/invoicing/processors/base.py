"""Normalized contract for payment processors.

Every concrete processor (FakeProcessor, LawPayProcessor, …) maps its own API
onto the value objects and statuses defined here, so callers stay
processor-agnostic. Money is always expressed in **integer cents** to match the
LawPay/AffiniPay charge API and to avoid float rounding.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# --- Normalized transaction statuses -------------------------------------
# A processor's native states (e.g. AffiniPay's AUTHORIZED/COMPLETED/RETURNED)
# collapse onto this small, stable set.
SUCCEEDED = "succeeded"  # funds captured/settled (card COMPLETED; ACH COMPLETED)
PENDING = "pending"  # accepted, awaiting settlement (ACH AUTHORIZED/PENDING)
FAILED = "failed"  # declined, or settlement failed (NSF, closed account)
RETURNED = "returned"  # reversed AFTER settlement (ACH return) — provisional PAID lost
REFUNDED = "refunded"  # refunded by us, in whole or part
VOIDED = "voided"  # cancelled before settlement

# Statuses that mean "we may record a Payment now." For card, the money is in;
# for ACH it is provisional until SUCCEEDED, but the invoice shows as paid.
ACCEPTED_STATUSES = frozenset({SUCCEEDED, PENDING})

# Statuses that mean "a previously-accepted charge fell through" — un-apply.
REVERSED_STATUSES = frozenset({FAILED, RETURNED, VOIDED})

# --- Payment method families ---------------------------------------------
CARD = "card"
BANK = "bank"  # ACH / eCheck


@dataclass
class ClientConfig:
    """Everything the client-side hosted-fields page needs to tokenize a
    payment. Returned by `PaymentProcessor.client_config()`; rendered into the
    public payment page. Contains no secrets — only the publishable key."""

    processor: str
    public_key: str
    amount_cents: int
    reference: str
    methods: list  # subset of [CARD, BANK]
    hosted_fields_url: str = ""
    # Offer eCheck/ACH in the payment form. Default off: the form is card-only
    # unless a processor opts in (the bank charge/recording path stays intact —
    # this only controls the visible form). LawPay's eCheck accounts are
    # currently suspended, so it stays off there until they're reactivated.
    echeck: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class ChargeResult:
    """Normalized result of a charge / fetch / refund."""

    processor: str
    transaction_id: str
    status: str  # one of the normalized statuses above
    amount_cents: int
    method: str  # CARD or BANK
    raw: dict = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        """True if a Payment should be recorded (card settled, or ACH pending)."""
        return self.status in ACCEPTED_STATUSES

    @property
    def is_pending(self) -> bool:
        """True for accepted-but-not-yet-settled charges (ACH in flight)."""
        return self.status == PENDING


@dataclass
class WebhookEvent:
    """Normalized, verified webhook event. Concrete processors build this only
    after confirming authenticity (for LawPay: by re-fetching the transaction
    from the API — the posted payload itself is not trusted)."""

    processor: str
    event_id: str
    transaction_id: str
    status: str  # one of the normalized statuses above
    amount_cents: int | None = None
    raw: dict = field(default_factory=dict)


# --- Exceptions ----------------------------------------------------------
class PaymentError(Exception):
    """Base for all processor errors."""


class ProcessorConfigError(PaymentError):
    """The processor is misconfigured (missing keys, unknown name, etc.)."""


class ChargeError(PaymentError):
    """A charge was declined or could not be created."""

    def __init__(self, message, *, code=None, raw=None):
        super().__init__(message)
        self.code = code
        self.raw = raw or {}


class WebhookVerificationError(PaymentError):
    """An incoming webhook could not be verified as authentic."""


class PaymentProcessor(ABC):
    """Abstract payment processor. Concrete adapters implement each operation
    against their own API and return the normalized value objects above."""

    #: short, stable identifier stored on Payment rows and used in webhook URLs
    name: str = ""

    @abstractmethod
    def client_config(self, invoice) -> ClientConfig:
        """Config for the client-side hosted-fields form for `invoice`."""

    @abstractmethod
    def charge(
        self,
        *,
        token: str,
        amount_cents: int,
        reference: str,
        method: str,
        idempotency_key: str | None = None,
        metadata: dict | None = None,
        trust: bool = False,
        client: dict | None = None,
        matter: dict | None = None,
    ) -> ChargeResult:
        """Charge a one-time `token` for `amount_cents`. Raises `ChargeError`
        on decline/failure. `client`/`matter` are optional descriptor dicts a
        processor may use to attach the payer to its records (ignored by those
        that don't)."""

    @abstractmethod
    def fetch_transaction(self, transaction_id: str) -> ChargeResult:
        """Fetch the authoritative current state of a transaction. Used to
        confirm webhooks rather than trusting their payload."""

    @abstractmethod
    def verify_and_parse_webhook(self, request) -> WebhookEvent:
        """Verify an incoming webhook request and return a normalized event.
        Raises `WebhookVerificationError` if it cannot be trusted."""

    @abstractmethod
    def refund(
        self,
        *,
        transaction_id: str,
        amount_cents: int | None = None,
        reference: str | None = None,
    ) -> ChargeResult:
        """Refund a charge in whole (`amount_cents=None`) or in part."""
