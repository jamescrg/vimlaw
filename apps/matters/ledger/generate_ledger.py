from tempfile import NamedTemporaryFile

from django.http import Http404
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.matters.ledger.get_ledger_data import get_ledger_data
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

    ledger_data = get_ledger_data(matter)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    context = {
        "matter": matter,
        "proceeding": proceeding,
    } | ledger_data

    html_string = render_to_string("matters/ledger/ledger.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
