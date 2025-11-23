from django.core.validators import MinValueValidator
from django.db import models

from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment


class PaymentApplication(models.Model):
    """
    Intermediate model tracking the allocation of payments to specific invoices.
    Represents the many-to-many relationship between payments and invoices
    with the specific amount applied from each payment to each invoice.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="applications",
        help_text="The source of the cash being applied",
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="applications",
        help_text="The invoice debt being reduced",
    )
    amount_applied = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text="The dollar amount from this payment applied to this invoice",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"${self.amount_applied} from Payment #{self.payment_id} to Invoice #{self.invoice_id}"

    class Meta:
        db_table = "app_invoicing_payment_application"
        indexes = [
            models.Index(fields=["payment"]),
            models.Index(fields=["invoice"]),
        ]
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "invoice"],
                name="unique_payment_invoice_application",
            )
        ]


class CreditApplication(models.Model):
    """
    Intermediate model tracking the allocation of credits to specific invoices.
    Represents the many-to-many relationship between credits and invoices
    with the specific amount applied from each credit to each invoice.
    """

    credit = models.ForeignKey(
        Credit,
        on_delete=models.CASCADE,
        related_name="applications",
        help_text="The source credit being applied",
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="credit_applications",
        help_text="The invoice debt being reduced",
    )
    amount_applied = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text="The dollar amount from this credit applied to this invoice",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"${self.amount_applied} from Credit #{self.credit_id} to Invoice #{self.invoice_id}"

    class Meta:
        db_table = "app_invoicing_credit_application"
        indexes = [
            models.Index(fields=["credit"]),
            models.Index(fields=["invoice"]),
        ]
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["credit", "invoice"],
                name="unique_credit_invoice_application",
            )
        ]
