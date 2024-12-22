import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http.response import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.matters.ledger.generate_ledger import generate_ledger
from apps.matters.ledger.get_ledger_data import get_ledger_data
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def ledger_index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    ledger_data = get_ledger_data(matter)

    context = {
        "app": "matters",
        "subapp": "ledger",
        "matter": matter,
        "proceeding": proceeding,
    } | ledger_data

    return render(request, "matters/ledger/main.html", context)


@login_required
def ledger_list(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    ledger_data = get_ledger_data(matter)

    context = {
        "app": "matters",
        "subapp": "ledger",
        "matter": matter,
        "proceeding": proceeding,
    } | ledger_data

    return render(request, "matters/ledger/list.html", context)


@login_required
def ledger_pdf(request, pk):
    matter = get_object_or_404(Matter, pk=pk)
    file = generate_ledger(matter.id, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Ledger - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response
