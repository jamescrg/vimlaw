from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.activity.time.models import TimeEntry
from apps.management.pagination import CustomPaginator
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
