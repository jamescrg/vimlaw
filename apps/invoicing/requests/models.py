"""A payment request: an outgoing ask for money, paid via a tokenized link.

Two kinds, distinguished by ``account``:
- **operating** — pay a matter's open balance (or a firm-set partial); the link
  records a Payment applied to the matter's invoices → operating account.
- **trust** — deposit a firm-set retainer for a client; the link records a trust
  ledger Deposit → trust account, no invoice application.

A request is created (status SENT) when the firm emails the client a pay link;
it flips to PAID when paid (see apps.invoicing.pay), recording the resulting
Payment (operating) or trust Transaction (trust). The signed token carries the
row's ``uuid``.
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords

from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter
from utils.models import AuditMixin

STATUS_CHOICES = (
    ("SENT", "Sent"),
    ("PAID", "Paid"),
    ("CANCELED", "Canceled"),
)

ACCOUNT_CHOICES = (
    ("operating", "Operating"),
    ("trust", "Trust"),
)


class PaymentRequest(AuditMixin, models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    # Destination + anchor. Operating → a matter's invoice payment; trust → a
    # client's retainer deposit.
    account = models.CharField(
        max_length=10, choices=ACCOUNT_CHOICES, default="operating"
    )
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payment_requests",
    )
    client = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="trust_requests",
    )
    amount_requested = models.DecimalField(max_digits=10, decimal_places=2)
    # One or more recipients, comma-joined (the "To" line).
    recipient_email = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="SENT")
    # Fulfillment link (set when the pay link is used): an operating request
    # links its Payment, a trust request links its trust Transaction.
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    trust_transaction = models.ForeignKey(
        "trust.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"Payment request #{self.id} - {self.target}"

    @property
    def is_trust(self):
        return self.account == "trust"

    @property
    def target(self):
        """The matter (operating) or client (trust) this request is for."""
        return self.client if self.is_trust else self.matter

    class Meta:
        db_table = "app_invoicing_payment_request"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["matter"]),
            models.Index(fields=["client"]),
            models.Index(fields=["account"]),
        ]
