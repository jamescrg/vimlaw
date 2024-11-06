from apps.intakes.filter_intakes import IntakeFilter
from apps.management.pagination import CustomPaginator


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

    pagination = CustomPaginator(intakes, per_page=10, request=request)

    table_data = {
        "pagination": pagination,
        "intakes": pagination.get_object_list(),
        "number_intakes": number_intakes,
    }

    return table_data
