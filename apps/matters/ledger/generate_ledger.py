from datetime import datetime
from tempfile import NamedTemporaryFile

from django.http import Http404
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.matters.ledger.get_ledger_data import get_ledger_data
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.trust.trust import get_confirmed_client_balance


def generate_ledger(matter_id, request):
    """
    Generate a PDF of the ledger for the given matter
    """
    try:
        matter = Matter.objects.get(pk=matter_id)
    except Matter.DoesNotExist:
        raise Http404("Matter does not exist")

    current_date = datetime.now().strftime("%Y-%m-%d")

    ledger_data = get_ledger_data(matter)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    context = {
        "matter": matter,
        "proceeding": proceeding,
        "current_date": current_date,
        "client_trust_balance": client_trust_balance,
    } | ledger_data

    html_string = render_to_string("matters/ledger/pdf.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
