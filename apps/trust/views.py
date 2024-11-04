from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

import apps.trust.trust as trust
from apps.contacts.models import Contact
from apps.management.pagination import CustomPaginator
from apps.trust.forms import TransactionForm
from apps.trust.models import Transaction


@login_required
def trust_index(request):
    context = {
        "app": "trust",
    }

    return render(request, "trust/main.html", context)


@login_required
def trust_list(request):
    request.session["trust_view"] = "summary"

    contacts = trust.get_clients_asymmetric()
    contacts = trust.get_pending_client_balances(contacts)
    contacts = trust.get_confirmed_client_balances(contacts)

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()

    pagination = CustomPaginator(contacts, per_page=50, request=request)

    context = {
        "app": "trust",
        "pagination": pagination,
        "contacts": pagination.object_list,
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
    }

    return render(request, "trust/summary.html", context)


@login_required
def history_index(request, interval="30days"):
    context = {
        "app": "trust",
        "interval": interval,
    }

    return render(request, "trust/history-index.html", context)


@login_required
def history(request, interval="30days"):
    request.session["trust_view"] = "history"
    request.session["interval"] = interval

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()
    transactions = trust.get_account_history(interval)

    page = request.GET.get("page")
    pagination = Paginator(transactions, per_page=50).get_page(page)

    context = {
        "app": "trust",
        "pagination": pagination,
        "interval": interval,
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
        "transactions": pagination.object_list,
    }

    return render(request, "trust/history.html", context)


@login_required
def client_index(request, id):
    client = get_object_or_404(Contact, pk=id)

    context = {
        "app": "trust",
        "client": client,
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
        "app": "trust",
        "client": client,
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
            elif trust_view == "summary":
                return HttpResponse(status=204, headers={"HX-Trigger": "trustChanged"})

    else:
        today = date.today().strftime("%Y-%m-%d")

        if client_id:
            client = Contact.objects.get(pk=client_id)
            form = TransactionForm(initial={"date": today, "contact": client})
        else:
            clients = Contact.objects.filter(client_status="Current").order_by("name")

            form = TransactionForm(
                initial={"date": today}, use_required_attribute=False
            )
            form.fields["contact"].queryset = clients

    context = {
        "app": "trust",
        "edit": False,
        "add": True,
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
        form = TransactionForm(instance=transaction, use_required_attribute=False)

    context = {
        "app": "trust",
        "edit": True,
        "add": False,
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


@login_required
def delete(request, id):
    trust_view = request.session.get("trust_view", "summary")

    Transaction.objects.get(pk=id).delete()

    if trust_view == "history":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustHistoryChanged"})
    elif trust_view == "client":
        return HttpResponse(status=204, headers={"HX-Trigger": "trustClientChanged"})
