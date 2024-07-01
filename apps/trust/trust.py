from datetime import date, timedelta

from django.shortcuts import get_object_or_404

from apps.contacts.models import Contact
from apps.trust.models import Transaction


def calculate_balance(transactions):
    bal = 0
    for transaction in transactions:
        if transaction.type == "Deposit":
            bal += transaction.amount
        elif transaction.type == "Withdrawal":
            bal -= transaction.amount
    return bal


def get_pending_client_balance(contact_id):
    contact = get_object_or_404(Contact, pk=contact_id)
    transactions = Transaction.objects.filter(contact=contact)
    balance = calculate_balance(transactions)
    return balance


def get_confirmed_client_balance(contact_id):
    contact = get_object_or_404(Contact, pk=contact_id)
    transactions = Transaction.objects.filter(contact=contact, confirmed=1)
    balance = calculate_balance(transactions)
    return balance


def get_asymmetric_client_balance(contact_id):
    """Get all entries in the trust table for a given contact.

    Params:
    contact_id(int): the id for a contact

    Returns:
    balance (int): the trust balance for the given client

    Notes:
    The balance includes (a) all deposits regardless of whether they are confirmed, but
    (b) only confirmed withdrawals

    This function is used in connection with get_clients_asymmetric.
    It helps to identify all cients with a pending trust balance greater than $0.
    This makes sure that new clients are included in the 'Account Summary' page.

    """

    contact = get_object_or_404(Contact, pk=contact_id)
    deposits = Transaction.objects.filter(contact=contact, type="Deposit")
    withdrawals = Transaction.objects.filter(
        contact=contact, type="Withdrawal", confirmed=1
    )

    total_deposits = calculate_balance(deposits)
    total_withdrawals = -1 * calculate_balance(withdrawals)  # note the negative
    balance = total_deposits - total_withdrawals
    return balance


def get_pending_client_balances(contacts):
    if contacts:
        for contact in contacts:
            contact["pending_client_balance"] = get_pending_client_balance(
                contact["id"]
            )
    return contacts


def get_confirmed_client_balances(contacts):
    if contacts:
        for contact in contacts:
            contact["confirmed_client_balance"] = get_confirmed_client_balance(
                contact["id"]
            )
    return contacts


def get_clients_asymmetric():
    """Get all contacts for which there is an entry in the trust table.

    Returns:
    current_contacts (list): Dicts with contact id, name, and balance

    """

    all_contacts = Transaction.objects.values("contact").distinct()

    current_contacts = []

    for contact in all_contacts:
        contact = Contact.objects.filter(pk=contact["contact"]).get()

        client_balance = get_asymmetric_client_balance(contact.id)

        if client_balance > 0:
            new_contact = {
                "id": contact.id,
                "name": contact.name,
                "bal": client_balance,
            }
            current_contacts.append(new_contact)

    # sort the list of dicts by the 'name' of each dict
    if current_contacts:
        current_contacts = sorted(current_contacts, key=lambda k: k["name"])

    return current_contacts or False


def get_pending_account_balance():
    transactions = Transaction.objects.all()
    balance = calculate_balance(transactions)
    return balance


def get_confirmed_account_balance():
    transactions = Transaction.objects.filter(confirmed=1)
    balance = calculate_balance(transactions)
    return balance


def get_client_history(contact_id):
    contact = get_object_or_404(Contact, pk=contact_id)
    transactions = Transaction.objects.filter(contact=contact)
    return transactions


def get_account_history(interval):
    today = date.today()
    thirty_days = today - timedelta(days=30)
    sixty_days = today - timedelta(days=60)

    if interval == "all":
        transactions = Transaction.objects.all()
    elif interval == "60days":
        transactions = Transaction.objects.filter(date__gt=sixty_days)
    else:
        transactions = Transaction.objects.filter(date__gt=thirty_days)
    transactions = transactions.order_by("-date", "-id")

    return transactions
