from operator import itemgetter

from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment


def get_ledger_data(matter):
    transactions = []
    balance = 0  # Initialize balance to prevent UnboundLocalError

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
            affects_balance = invoice.status not in ["DRAFT", "APPROVED"]
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date_issued,
                "transaction_type": "Charge",
                "description": f"Invoice {invoice.id}",
                "amount": invoice.value["final_total"],
                "invoice_status": invoice.status,
                "affects_balance": affects_balance,
            }
            transactions.append(invoice_dict)

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
        "total_credits": total_credits,
    }
