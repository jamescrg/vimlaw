import os
from datetime import datetime
from operator import itemgetter

from django.contrib.auth.decorators import login_required
from django.http.response import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.billing.invoices.models import Invoice
from apps.billing.payments.models import Payment
from apps.matters.ledger.generate_ledger import generate_ledger
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    transactions = []
    balance_due = 0

    invoices = Invoice.objects.filter(matter=matter).order_by("date_issued") or None
    payments = Payment.objects.filter(matter=matter).order_by("date") or None

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
            balance_due -= invoice.amount

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

    if transactions:
        transactions = sorted(transactions, key=itemgetter("transaction_type"))
        transactions = sorted(transactions, key=itemgetter("date"))

    context = {
        "app": "matters",
        "subapp": "ledger",
        "matter": matter,
        "proceeding": proceeding,
        "transactions": transactions,
        "balance_due": -1 * float(balance_due),
    }

    return render(request, "matters/ledger/list.html", context)


@login_required
def ledger_pdf(request, pk):
    matter = get_object_or_404(Matter, pk=pk)
    file = generate_ledger(matter.id, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Ledger - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = filename

    os.unlink(file.name)

    return response
