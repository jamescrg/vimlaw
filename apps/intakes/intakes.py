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

    pagination = CustomPaginator(
        intakes, per_page=10, request=request, session_key="intake_pagination"
    )

    table_data = {
        "pagination": pagination,
        "intakes": pagination.get_object_list(),
        "session_key": "intake_pagination",
        "trigger_key": "intakesChanged",
        "number_intakes": number_intakes,
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
    }

    return table_data
