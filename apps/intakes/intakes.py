from django.core.paginator import Paginator

from apps.intakes.filter_intakes import IntakeFilter


def get_table_data(request):
    table_data = {}

    default_filter = {"status": "Open"}

    filter_data = request.session.get("intake_filter", None)

    if filter_data:
        filter = IntakeFilter(filter_data)
        intakes = filter.qs
    else:
        filter = IntakeFilter(default_filter)
        intakes = filter.qs

    request.session["intake_filter"] = filter.data
    request.session.modified = True

    number_intakes = intakes.count()

    page = request.GET.get("page")
    pagination = Paginator(intakes, per_page=10).get_page(page)

    table_data = {
        "pagination": pagination,
        "intakes": pagination.object_list,
        "number_intakes": number_intakes,
    }

    return table_data
