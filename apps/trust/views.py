import csv

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

import apps.trust.trust as trust
from apps.contacts.models import Contact
from apps.management.pagination import CustomPaginator
from apps.trust.forms import TransactionForm
from apps.trust.get_trust_data import get_trust_data
from apps.trust.models import Transaction


@login_required
def trust_index(request):
    request.session["trust_view"] = "summary"

    trust_data = get_trust_data(request)

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "page": "summary",
    } | trust_data

    return render(request, "trust/main.html", context)


@login_required
def trust_list(request):
    request.session["trust_view"] = "summary"

    trust_data = get_trust_data(request)

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "page": "summary",
    }

    context = context | trust_data

    return render(request, "trust/summary.html", context)


@login_required
def order_by(request, order):
    """Toggle the Account Summary sort. Stores the chosen key in the session
    (repeat click flips to descending) and re-renders via the trustChanged
    trigger; get_trust_data applies it to the list of client rows."""
    current = request.session.get("trust_order", "")
    if current == order:
        new_order = f"-{order}" if not current.startswith("-") else order
    else:
        new_order = order
    request.session["trust_order"] = new_order
    return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})


@login_required
def history_csv(request):
    """Download the entire trust ledger as CSV for reconciliation against the
    bank record. Rows are oldest-first, and withdrawals are signed negative
    (matching a bank statement) so the Amount column sums to the net account
    movement; the Type column is kept for readability. Always the full ledger,
    regardless of the on-screen interval filter."""
    transactions = Transaction.objects.select_related("contact").order_by("date", "id")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="trust-ledger-{timezone.localdate():%Y-%m-%d}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "Client ID",
            "Date",
            "Client Name",
            "Description",
            "Method",
            "Amount",
            "Type",
            "Confirmed",
        ]
    )
    for t in transactions:
        amount = t.amount or 0
        signed = -amount if t.type == "Withdrawal" else amount
        writer.writerow(
            [
                t.contact_id or "",
                t.date.isoformat() if t.date else "",
                t.contact.name if t.contact else "",
                t.description or "",
                t.get_method_display(),
                f"{signed:.2f}",
                t.type or "",
                "Yes" if t.confirmed else "No",
            ]
        )
    return response


@login_required
def history_index(request, interval="30days"):
    request.session["trust_view"] = "history"
    request.session["interval"] = interval

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()
    transactions = trust.get_account_history(interval)

    pagination = CustomPaginator(
        transactions,
        per_page=50,
        request=request,
        session_key="trust_history_pagination",
    )

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "page": "history",
        "session_key": "trust_history_pagination",
        "trigger_key": "trustHistoryChanged",
        "interval": interval,
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
        "transactions": pagination.get_object_list(),
    }

    return render(request, "trust/history-index.html", context)


@login_required
def history(request, interval="30days"):
    request.session["trust_view"] = "history"
    request.session["interval"] = interval

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()
    transactions = trust.get_account_history(interval)

    pagination = CustomPaginator(
        transactions,
        per_page=50,
        request=request,
        session_key="trust_history_pagination",
    )

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "pagination": pagination,
        "page": "history",
        "interval": interval,
        "session_key": "trust_history_pagination",
        "trigger_key": "trustHistoryChanged",
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
        "transactions": pagination.get_object_list(),
    }

    return render(request, "trust/history.html", context)


@login_required
def client_index(request, id):
    request.session["trust_view"] = "client"

    client = get_object_or_404(Contact, pk=id)

    pending_client_balance = trust.get_pending_client_balance(id)
    confirmed_client_balance = trust.get_confirmed_client_balance(id)
    transactions = trust.get_client_history(id)

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "client": client,
        "page": "client",
        "pending_client_balance": pending_client_balance,
        "confirmed_client_balance": confirmed_client_balance,
        "transactions": transactions,
    }

    return render(request, "trust/client-index.html", context)


@login_required
def client(request, id):
    request.session["trust_view"] = "client"

    client = get_object_or_404(Contact, pk=id)
    pending_client_balance = trust.get_pending_client_balance(id)
    confirmed_client_balance = trust.get_confirmed_client_balance(id)
    transactions = trust.get_client_history(id)

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "client": client,
        "page": "client",
        "pending_client_balance": pending_client_balance,
        "confirmed_client_balance": confirmed_client_balance,
        "transactions": transactions,
    }

    return render(request, "trust/client.html", context)


@login_required
def add(request, client_id=None):
    trust_view = request.session.get("trust_view", "summary")

    if request.method == "POST":
        form = TransactionForm(request.POST, use_required_attribute=False)

        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.save()

            if trust_view == "client":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "trustClientChanged"}
                )
            elif trust_view == "history":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "trustHistoryChanged"}
                )
            else:
                return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})

    else:
        today = timezone.localdate().strftime("%Y-%m-%d")

        if client_id:
            client = Contact.objects.get(pk=client_id)
            form = TransactionForm(initial={"date": today, "contact": client})
        else:
            clients = Contact.objects.current_clients().order_by("name")

            form = TransactionForm(
                initial={"date": today}, use_required_attribute=False
            )
            form.fields["contact"].queryset = clients

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "edit": False,
        "add": True,
        "action": "/invoicing/trust/add",
        "form": form,
    }

    return render(request, "trust/form.html", context)


@login_required
def edit(request, id):
    trust_view = request.session.get("trust_view", "summary")
    transaction = get_object_or_404(Transaction, pk=id)

    if request.method == "POST":
        form = TransactionForm(
            request.POST, instance=transaction, use_required_attribute=False
        )

        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.save()

            if trust_view == "history":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "trustHistoryChanged"}
                )
            elif trust_view == "client":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "trustClientChanged"}
                )
            else:
                return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})

    else:
        form = TransactionForm(instance=transaction, use_required_attribute=False)

    context = {
        "app": "invoicing",
        "subapp": "trust",
        "edit": True,
        "add": False,
        "action": f"/invoicing/trust/{id}/edit",
        "transaction": transaction,
        "form": form,
    }

    return render(request, "trust/form.html", context)


@login_required
def toggle_entered(request, id):
    trust_view = request.session.get("trust_view", "summary")
    transaction = get_object_or_404(Transaction, pk=id)

    if transaction.entered == 1:
        transaction.entered = 0
    else:
        transaction.entered = 1
    transaction.save()

    if trust_view == "history":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustHistoryChanged"})
    elif trust_view == "client":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustClientChanged"})
    else:
        return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})


@login_required
def toggle_confirmed(request, id):
    trust_view = request.session.get("trust_view", "summary")
    transaction = get_object_or_404(Transaction, pk=id)

    if transaction.confirmed == 1:
        transaction.confirmed = 0
    else:
        transaction.confirmed = 1
    transaction.save()

    if trust_view == "history":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustHistoryChanged"})
    elif trust_view == "client":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustClientChanged"})
    else:
        return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})


@login_required
def delete(request, id):
    trust_view = request.session.get("trust_view", "summary")

    Transaction.objects.get(pk=id).delete()

    if trust_view == "history":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustHistoryChanged"})
    elif trust_view == "client":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustClientChanged"})
    else:
        return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})
