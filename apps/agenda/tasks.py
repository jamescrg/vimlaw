from dateutil import parser

from django.shortcuts import get_object_or_404

from apps.matters.models import Matter
from apps.agenda.models import Task
from apps.accounts.models import CustomUser
from apps.agenda.filter import Filter


def get_table_data(request):

    table_data = {}

    tasks = Task.objects.all().order_by("-status", "description")

    filter = Filter(request).values

    if filter["date_from"]:
        if type(filter["date_from"]) == str:
            filter["date_from"] = parser.parse(filter["date_from"])
        tasks = tasks.filter(date_due__gte=filter["date_from"])

    if filter["date_to"]:
        if type(filter["date_to"]) == str:
            filter["date_to"] = parser.parse(filter["date_to"])
        tasks = tasks.filter(date_due__lte=filter["date_to"])

    if filter["status"]:
        tasks = tasks.filter(status=filter["status"])

    if filter["matter"]:
        matter = get_object_or_404(Matter, pk=filter["matter"])
        tasks = tasks.filter(matter=matter)

    if filter["user"]:
        user = get_object_or_404(CustomUser, pk=filter["user"])
        tasks = tasks.filter(user=user)

    order = filter["order_field"]
    if order == "matter":
        order = "matter__name"
    if filter["order_direction"] == "descending":
        order = f"-{order}"
    tasks = tasks.order_by("-priority", order)

    table_data["tasks"] = tasks
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
