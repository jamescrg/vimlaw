from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

import apps.trust.trust as trust
from apps.contacts.models import Contact
from apps.trust.forms import TransactionForm
from apps.trust.models import Transaction


def trust_redirect(request, transaction):
    if request.session.get("trust_view") == "client":
        return redirect(f"/trust/client/{transaction.contact.id}")
    elif request.session.get("trust_view") == "history":
        interval = request.session["interval"]
        return redirect(f"/trust/history/{interval}")
    else:
        return redirect("/trust")


@login_required
def index(request):
    request.session["trust_view"] = "summary"

    contacts = trust.get_clients_asymmetric()
    contacts = trust.get_pending_client_balances(contacts)
    contacts = trust.get_confirmed_client_balances(contacts)

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()

    page = request.GET.get("page")
    pagination = Paginator(contacts, per_page=10).get_page(page)

    context = {
        "page": "trust",
        "pagination": pagination,
        "contacts": pagination.object_list,
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
    }

    return render(request, "trust/summary.html", context)


@login_required
def history(request, interval="30days"):
    request.session["trust_view"] = "history"
    request.session["interval"] = interval

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()
    transactions = trust.get_account_history(interval)

    page = request.GET.get("page")
    pagination = Paginator(transactions, per_page=10).get_page(page)

    context = {
        "page": "trust",
        "pagination": pagination,
        "interval": interval,
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
        "transactions": pagination.object_list,
    }

    return render(request, "trust/history.html", context)


@login_required
def client(request, id):
    request.session["trust_view"] = "client"

    client = get_object_or_404(Contact, pk=id)
    pending_client_balance = trust.get_pending_client_balance(id)
    confirmed_client_balance = trust.get_confirmed_client_balance(id)
    transactions = trust.get_client_history(id)

    context = {
        "page": "trust",
        "client": client,
        "pending_client_balance": pending_client_balance,
        "confirmed_client_balance": confirmed_client_balance,
        "transactions": transactions,
    }

    return render(request, "trust/client.html", context)


@login_required
def add(request, client_id=None):
    if request.method == "POST":
        form = TransactionForm(request.POST)

        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.save()

            return redirect("trust:trust")

    else:
        today = date.today().strftime("%Y-%m-%d")

        if client_id:
            client = Contact.objects.get(pk=client_id)
            form = TransactionForm(initial={"date": today, "contact": client})
        else:
            clients = Contact.objects.filter(client_status="Current").order_by("name")

            form = TransactionForm(initial={"date": today})
            form.fields["contact"].queryset = clients

    context = {
        "page": "trust",
        "edit": False,
        "add": True,
        "form": form,
    }

    return render(request, "trust/form.html", context)


@login_required
def edit(request, id):
    transaction = get_object_or_404(Transaction, pk=id)

    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)

        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.save()

            return redirect(f"/trust/client/{transaction.contact.id}")

    else:
        form = TransactionForm(instance=transaction)

    context = {
        "page": "trust",
        "edit": True,
        "add": False,
        "transaction": transaction,
        "form": form,
    }

    return render(request, "trust/form.html", context)


@login_required
def toggle_entered(request, id):
    transaction = get_object_or_404(Transaction, pk=id)
    if transaction.entered == 1:
        transaction.entered = 0
    else:
        transaction.entered = 1
    transaction.save()
    return trust_redirect(request, transaction)


@login_required
def toggle_confirmed(request, id):
    transaction = get_object_or_404(Transaction, pk=id)
    if transaction.confirmed == 1:
        transaction.confirmed = 0
    else:
        transaction.confirmed = 1
    transaction.save()
    return trust_redirect(request, transaction)


@login_required
def delete(request, id):
    transaction = get_object_or_404(Transaction, pk=id)
    transaction.delete()
    return trust_redirect(request, transaction)
