from operator import itemgetter
from tempfile import NamedTemporaryFile

from django.http import Http404
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.billing.invoices.models import Invoice
from apps.billing.payments.models import Payment
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


def generate_ledger(matter_id, request):
    """
    Generate a PDF of the ledger for the given matter
    """
    try:
        matter = Matter.objects.get(pk=matter_id)
    except Matter.DoesNotExist:
        raise Http404("Matter does not exist")

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
        "matter": matter,
        "proceeding": proceeding,
        "transactions": transactions,
        "balance_due": -1 * float(balance_due),
    }

    html_string = render_to_string("matters/ledger/ledger.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
