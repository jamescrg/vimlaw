import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.activity.time.models import TimeEntry
from apps.management.pagination import CustomPaginator
from apps.matters.generate_activity_report import generate_activity_report
from apps.matters.ledger.get_ledger_data import get_ledger_data
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.trust.trust import get_confirmed_client_balance


@login_required
def activity_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id, primary=True).first()

    entries = TimeEntry.objects.filter(matter=id).order_by("-id")

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    # Get balance due from ledger
    ledger_data = get_ledger_data(matter)
    balance_due = ledger_data.get("balance_due", 0)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "proceeding": proceeding,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "client_trust_balance": client_trust_balance,
        "balance_due": balance_due,
    }

    return render(request, "matters/activity/main.html", context)


@login_required
def activity_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    entries = TimeEntry.objects.filter(matter=id).order_by("-id")

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    # Get balance due from ledger
    ledger_data = get_ledger_data(matter)
    balance_due = ledger_data.get("balance_due", 0)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "proceeding": proceeding,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "client_trust_balance": client_trust_balance,
        "balance_due": balance_due,
    }

    return render(request, "matters/activity/list.html", context)


@login_required
def activity_report(request, id):
    matter = get_object_or_404(Matter, pk=id)
    file = generate_activity_report(matter, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Activity Report - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response
