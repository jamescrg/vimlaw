from tempfile import NamedTemporaryFile

from django.http.response import Http404
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.timeline.models import Fact


def generate_timeline(matter_id, request):
    """
    Generate a timeline PDF for the given matter
    """
    try:
        matter = Matter.objects.get(pk=matter_id)
    except Matter.DoesNotExist:
        raise Http404("Matter does not exist")

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    facts = Fact.objects.filter(matter=matter.id).order_by("date")

    context = {
        "matter": matter,
        "proceeding": proceeding,
        "facts": facts,
    }

    html_string = render_to_string("matters/timeline/timeline.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
