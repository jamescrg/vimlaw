import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.http.response import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.access import matter_access_required
from apps.matters.ledger.generate_ledger import generate_ledger
from apps.matters.ledger.get_ledger_data import get_ledger_data
from apps.matters.models import Matter
from apps.trust.available import client_trust_available, trust_available_severity
from apps.trust.trust import get_pending_client_balance


def _check_financial_perm(request):
    if not request.user.is_admin and not request.user.perm_financial:
        return HttpResponseForbidden()
    return None


@login_required
@matter_access_required
def ledger_index(request, id):
    forbidden = _check_financial_perm(request)
    if forbidden:
        return forbidden
    matter = get_object_or_404(Matter, pk=id)
    ledger_data = get_ledger_data(matter)

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_pending_client_balance(matter.client.id)

    total_cost = (
        matter.value["invoices"]["payment_sum"]
        + ledger_data["balance_due"]
        + matter.value["unbilled"]["net_fees_and_expenses"]
    )

    trust_available = client_trust_available(matter.client_id)
    context = {
        "app": "matters",
        "subapp": "ledger",
        "matter": matter,
        "client_trust_balance": client_trust_balance,
        "trust_available": trust_available,
        "trust_available_severity": trust_available_severity(
            trust_available, client_trust_balance
        ),
        "total_cost": total_cost,
    } | ledger_data

    return render(request, "matters/ledger/main.html", context)


@login_required
@matter_access_required
def ledger_list(request, id):
    forbidden = _check_financial_perm(request)
    if forbidden:
        return forbidden
    matter = get_object_or_404(Matter, pk=id)
    ledger_data = get_ledger_data(matter)

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_pending_client_balance(matter.client.id)

    trust_available = client_trust_available(matter.client_id)
    context = {
        "app": "matters",
        "subapp": "ledger",
        "matter": matter,
        "client_trust_balance": client_trust_balance,
        "trust_available": trust_available,
        "trust_available_severity": trust_available_severity(
            trust_available, client_trust_balance
        ),
    } | ledger_data

    return render(request, "matters/ledger/list.html", context)


@login_required
@matter_access_required
def ledger_pdf(request, id):
    forbidden = _check_financial_perm(request)
    if forbidden:
        return forbidden
    matter = get_object_or_404(Matter, pk=id)
    file = generate_ledger(matter.id, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Ledger - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response
