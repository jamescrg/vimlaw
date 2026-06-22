from operator import itemgetter

from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment


def get_ledger_data(matter):
    """Build the matter ledger.

    ``balance_due`` is the full running balance and INCLUDES deferred invoices.

    Deferred-fee arrangements (invoices manually marked ``DEFERRED``) are also
    broken out so the ledger can distinguish the accumulated recovery claim from
    what the client owes right now, and so trust clearance is not dragged down by
    fees the client is not currently obligated to pay:

    - ``deferred_total``   -- net recovery claim: sum of ``amount_remaining`` over
      ``DEFERRED`` invoices (i.e. after the client's payments/credits applied to them).
    - ``currently_owed``   -- sum of ``amount_remaining`` over non-deferred displayed
      invoices: what the client owes now. Used for the trust-clearance figure.
    - ``has_deferred``     -- whether this matter has any deferred recovery claim.

    When payments/credits are fully applied to invoices,
    ``currently_owed + deferred_total`` reconciles to ``balance_due``.
    """
    transactions = []
    balance = 0  # Initialize balance to prevent UnboundLocalError
    deferred_total = 0
    currently_owed = 0

    # Only include invoices that should be displayed in ledger (exclude DRAFT and APPROVED)
    invoices = (
        Invoice.objects.filter(matter=matter)
        .exclude(status__in=["DRAFT", "APPROVED"])
        .order_by("date_issued")
        or None
    )
    payments = Payment.objects.filter(matter=matter).order_by("date") or None
    credits = Credit.objects.filter(matter=matter).order_by("date") or None

    # Add invoices to transactions (exclude DRAFT and APPROVED)
    if invoices:
        for invoice in invoices:
            affects_balance = invoice.status not in [
                "DRAFT",
                "APPROVED",
                "VOID",
                "UNCOLLECTIBLE",
            ]
            is_deferred = invoice.status == "DEFERRED"
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date_issued,
                "transaction_type": "Charge",
                "description": f"Invoice {invoice.id}",
                "amount": invoice.value["final_total"],
                "invoice_status": invoice.status,
                "is_deferred": is_deferred,
                "affects_balance": affects_balance,
            }
            transactions.append(invoice_dict)

            # Break out the deferred recovery claim vs. what is currently owed,
            # netting payments/credits already applied to each invoice.
            if is_deferred:
                deferred_total += invoice.amount_remaining
            else:
                currently_owed += invoice.amount_remaining

    if payments:
        for payment in payments:
            payment_dict = {
                "id": payment.id,
                "date": payment.date,
                "transaction_type": "Credit",
                "description": f"Payment by {payment.payment_method.lower()}",
                "amount": payment.amount,
                "affects_balance": True,  # Payments always affect balance
            }
            transactions.append(payment_dict)

    if credits:
        for credit in credits:
            credit_dict = {
                "id": credit.id,
                "date": credit.date,
                "transaction_type": "Credit",
                "description": credit.detail,
                "amount": credit.amount,
                "affects_balance": True,  # Credits always affect balance
            }
            transactions.append(credit_dict)

    if transactions:
        transactions = sorted(transactions, key=itemgetter("transaction_type"))
        transactions = sorted(transactions, key=itemgetter("date"))

        # Calculate balance for each transaction (only counting those that affect balance)
        balance = 0
        for transaction in transactions:
            if transaction.get(
                "affects_balance", True
            ):  # Default to True for backwards compatibility
                if transaction["transaction_type"] == "Charge":
                    balance += transaction["amount"]
                else:
                    balance -= transaction["amount"]
            transaction["balance"] = balance

    # Calculate total credits
    total_credits = sum(c.amount for c in credits) if credits else 0

    return {
        "transactions": transactions,
        "balance_due": balance,
        "deferred_total": deferred_total,
        "currently_owed": currently_owed,
        "has_deferred": bool(deferred_total),
        "total_credits": total_credits,
    }
