from operator import itemgetter

from apps.billing.credits.models import Credit
from apps.billing.invoices.models import Invoice
from apps.billing.payments.models import Payment


def get_ledger_data(matter):
    transactions = []
    balance_due = 0

    invoices = Invoice.objects.filter(matter=matter).order_by("date_issued") or None
    payments = Payment.objects.filter(matter=matter).order_by("date") or None
    credits = Credit.objects.filter(matter=matter).order_by("date") or None

    if invoices:
        for invoice in invoices:
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date_issued,
                "transaction_type": "Charge",
                "description": f"Invoice {invoice.id}",
                "amount": invoice.value["final_total"],
            }
            transactions.append(invoice_dict)
            balance_due -= invoice.value["final_total"]

    if payments:
        for payment in payments:
            payment_dict = {
                "id": payment.id,
                "date": payment.date,
                "transaction_type": "Credit",
                "description": f"Payment by {payment.payment_method.lower()}",
                "amount": payment.amount,
            }
            transactions.append(payment_dict)
            balance_due += payment.amount

    if credits:
        for credit in credits:
            credit_dict = {
                "id": credit.id,
                "date": credit.date,
                "transaction_type": "Credit",
                "description": f"Credit {credit.id}",
                "amount": credit.amount,
            }
            transactions.append(credit_dict)
            balance_due += credit.amount

    if transactions:
        transactions = sorted(transactions, key=itemgetter("transaction_type"))
        transactions = sorted(transactions, key=itemgetter("date"))

    return {
        "transactions": transactions,
        "balance_due": -1 * float(balance_due),
    }
