from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.matters.events.get_event_data import get_event_data
from apps.matters.ledger.get_ledger_data import get_ledger_data
from apps.matters.models import Matter
from apps.trust.trust import get_confirmed_client_balance


@login_required
def events_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    event_data = get_event_data(matter)

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    # Get balance due from ledger
    ledger_data = get_ledger_data(matter)
    balance_due = ledger_data.get("balance_due", 0)

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
        "client_trust_balance": client_trust_balance,
        "balance_due": balance_due,
    } | event_data

    return render(request, "matters/events/main.html", context)


@login_required
def events_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    event_data = get_event_data(matter)

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    # Get balance due from ledger
    ledger_data = get_ledger_data(matter)
    balance_due = ledger_data.get("balance_due", 0)

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
        "client_trust_balance": client_trust_balance,
        "balance_due": balance_due,
    }

    context = context | event_data

    return render(request, "matters/events/list.html", context)
