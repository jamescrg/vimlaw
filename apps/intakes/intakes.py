from django.core.paginator import Paginator

from apps.intakes.filter_intakes import IntakeFilter
from apps.intakes.models import Intake


def get_table_data(request):
    table_data = {}

    filter_data = request.session.get("intake_filter", None)

    if filter_data:
        filter = IntakeFilter(filter_data)
        intakes = filter.qs
    else:
        intakes = Intake.objects.all().order_by("-date")

    number_intakes = intakes.count()

    page = request.GET.get("page")
    pagination = Paginator(intakes, per_page=10).get_page(page)

    table_data = {
        "pagination": pagination,
        "intakes": pagination.object_list,
        "number_intakes": number_intakes,
    }

    return table_data
