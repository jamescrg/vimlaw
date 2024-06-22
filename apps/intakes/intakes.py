

from dateutil import parser
from django.contrib.auth.decorators import login_required

from apps.intakes.filter import Filter
from apps.intakes.models import Intake


def get_table_data(request):

    table_data = {}

    intakes = Intake.objects.all()

    filter = Filter(request).values

    if filter["date_from"]:
        filter["date_from"] = parser.parse(filter["date_from"])

    if filter["date_to"]:
        filter["date_to"] = parser.parse(filter["date_to"])

    intakes = Intake.objects.all()

    if filter["status"]:
        intakes = intakes.filter(status=filter["status"])
    if filter["date_from"]:
        intakes = intakes.filter(date__gt=filter["date_from"])
    if filter["date_to"]:
        intakes = intakes.filter(date__lt=filter["date_to"])
    if filter["area"]:
        intakes = intakes.filter(practice_area=filter["area"])
    if filter["source"]:
        intakes = intakes.filter(source=filter["source"])
    if filter["order"] == "name":
        intakes = intakes.order_by("name")
    else:
        intakes = intakes.order_by("-date", "-id")

    if filter["limit"]:
        intakes = intakes[: filter["limit"]]

    number_intakes = intakes.count()

    table_data = {
        "intakes": intakes,
        "number_intakes": number_intakes,
    }

    return table_data
