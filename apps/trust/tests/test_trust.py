from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.trust.models import Transaction
from apps.trust.trust import (
    calculate_balance,
    get_account_history,
    get_asymmetric_client_balance,
    get_client_history,
    get_clients_asymmetric,
    get_confirmed_account_balance,
    get_confirmed_client_balance,
    get_confirmed_client_balances,
    get_pending_account_balance,
    get_pending_client_balance,
    get_pending_client_balances,
)

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# calculate_balance
# -----------------------------------------------------------
class TestCalculateBalance:
    def test_empty_transactions(self):
        assert calculate_balance([]) == 0

    def test_single_deposit(self, contact):
        txns = [Transaction(contact=contact, type="Deposit", amount=Decimal("500.00"))]
        assert calculate_balance(txns) == Decimal("500.00")

    def test_single_withdrawal(self, contact):
        txns = [
            Transaction(contact=contact, type="Withdrawal", amount=Decimal("200.00"))
        ]
        assert calculate_balance(txns) == Decimal("-200.00")

    def test_deposits_and_withdrawals(self, contact):
        txns = [
            Transaction(contact=contact, type="Deposit", amount=Decimal("1000.00")),
            Transaction(contact=contact, type="Withdrawal", amount=Decimal("300.00")),
            Transaction(contact=contact, type="Deposit", amount=Decimal("200.00")),
        ]
        assert calculate_balance(txns) == Decimal("900.00")

    def test_balance_goes_negative(self, contact):
        txns = [
            Transaction(contact=contact, type="Deposit", amount=Decimal("100.00")),
            Transaction(contact=contact, type="Withdrawal", amount=Decimal("500.00")),
        ]
        assert calculate_balance(txns) == Decimal("-400.00")

    def test_multiple_deposits_no_withdrawals(self, contact):
        txns = [
            Transaction(contact=contact, type="Deposit", amount=Decimal("100.00")),
            Transaction(contact=contact, type="Deposit", amount=Decimal("200.00")),
            Transaction(contact=contact, type="Deposit", amount=Decimal("300.00")),
        ]
        assert calculate_balance(txns) == Decimal("600.00")


# -----------------------------------------------------------
# get_pending_client_balance
# -----------------------------------------------------------
class TestGetPendingClientBalance:
    def test_single_deposit(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("2000.00"),
            confirmed=False,
        )
        assert get_pending_client_balance(contact.id) == Decimal("2000.00")

    def test_includes_confirmed_and_unconfirmed(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("500.00"),
            confirmed=False,
        )
        assert get_pending_client_balance(contact.id) == Decimal("1500.00")

    def test_deposits_minus_withdrawals(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("3000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Withdrawal",
            amount=Decimal("750.00"),
            confirmed=False,
        )
        assert get_pending_client_balance(contact.id) == Decimal("2250.00")

    def test_no_transactions_returns_zero(self, contact):
        assert get_pending_client_balance(contact.id) == 0

    def test_nonexistent_contact_raises_404(self):
        from django.http import Http404

        with pytest.raises(Http404):
            get_pending_client_balance(99999)


# -----------------------------------------------------------
# get_confirmed_client_balance
# -----------------------------------------------------------
class TestGetConfirmedClientBalance:
    def test_only_confirmed_transactions(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("500.00"),
            confirmed=False,
        )
        assert get_confirmed_client_balance(contact.id) == Decimal("1000.00")

    def test_confirmed_deposits_and_withdrawals(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("2000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Withdrawal",
            amount=Decimal("500.00"),
            confirmed=True,
        )
        assert get_confirmed_client_balance(contact.id) == Decimal("1500.00")

    def test_excludes_unconfirmed_withdrawals(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("2000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Withdrawal",
            amount=Decimal("500.00"),
            confirmed=False,
        )
        assert get_confirmed_client_balance(contact.id) == Decimal("2000.00")

    def test_no_confirmed_returns_zero(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=False,
        )
        assert get_confirmed_client_balance(contact.id) == 0


# -----------------------------------------------------------
# get_asymmetric_client_balance
# -----------------------------------------------------------
class TestGetAsymmetricClientBalance:
    def test_all_deposits_only_confirmed_withdrawals(self, contact):
        """Asymmetric balance = all deposits - confirmed withdrawals only."""
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("3000.00"),
            confirmed=False,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Withdrawal",
            amount=Decimal("500.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-03",
            type="Withdrawal",
            amount=Decimal("200.00"),
            confirmed=False,
        )
        # Deposit $3000 - confirmed withdrawal $500 = $2500
        # Unconfirmed withdrawal of $200 is excluded
        assert get_asymmetric_client_balance(contact.id) == Decimal("2500.00")

    def test_no_withdrawals(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=False,
        )
        assert get_asymmetric_client_balance(contact.id) == Decimal("1000.00")

    def test_no_transactions(self, contact):
        assert get_asymmetric_client_balance(contact.id) == 0

    def test_unconfirmed_deposit_included(self, contact):
        """Even unconfirmed deposits are included in the asymmetric balance."""
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("2000.00"),
            confirmed=False,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        assert get_asymmetric_client_balance(contact.id) == Decimal("3000.00")


# -----------------------------------------------------------
# get_pending_account_balance / get_confirmed_account_balance
# -----------------------------------------------------------
class TestAccountBalances:
    def test_pending_account_balance(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("5000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("3000.00"),
            confirmed=False,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-03",
            type="Withdrawal",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        assert get_pending_account_balance() == Decimal("7000.00")

    def test_confirmed_account_balance(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("5000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("3000.00"),
            confirmed=False,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-03",
            type="Withdrawal",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        assert get_confirmed_account_balance() == Decimal("4000.00")

    def test_empty_account(self):
        assert get_pending_account_balance() == 0
        assert get_confirmed_account_balance() == 0

    def test_multi_client_account_balance(self, contact, folder, user):
        from apps.contacts.models import Contact

        contact2 = Contact.objects.create(user=user, folder=folder, name="Client Two")
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact2,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("2000.00"),
            confirmed=True,
        )
        assert get_pending_account_balance() == Decimal("3000.00")
        assert get_confirmed_account_balance() == Decimal("3000.00")


# -----------------------------------------------------------
# get_pending_client_balances / get_confirmed_client_balances
# -----------------------------------------------------------
class TestBulkClientBalances:
    def test_pending_client_balances(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1500.00"),
            confirmed=False,
        )
        contacts = [{"id": contact.id}]
        result = get_pending_client_balances(contacts)
        assert result[0]["pending_client_balance"] == Decimal("1500.00")

    def test_confirmed_client_balances(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("500.00"),
            confirmed=False,
        )
        contacts = [{"id": contact.id}]
        result = get_confirmed_client_balances(contacts)
        assert result[0]["confirmed_client_balance"] == Decimal("1000.00")

    def test_empty_list(self):
        assert get_pending_client_balances([]) == []
        assert get_confirmed_client_balances([]) == []

    def test_none_input(self):
        assert get_pending_client_balances(None) is None
        assert get_confirmed_client_balances(None) is None


# -----------------------------------------------------------
# get_clients_asymmetric
# -----------------------------------------------------------
class TestGetClientsAsymmetric:
    def test_returns_clients_with_nonzero_balance(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("2000.00"),
            confirmed=False,
        )
        result = get_clients_asymmetric()
        assert len(result) == 1
        assert result[0]["id"] == contact.id
        assert result[0]["name"] == contact.name
        assert result[0]["bal"] == Decimal("2000.00")

    def test_excludes_zero_balance_clients(self, contact):
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Withdrawal",
            amount=Decimal("1000.00"),
            confirmed=True,
        )
        result = get_clients_asymmetric()
        assert len(result) == 0

    def test_sorted_by_name(self, contact, folder, user):
        from apps.contacts.models import Contact

        contact_b = Contact.objects.create(
            user=user, folder=folder, name="Zebra Client"
        )
        contact_a = Contact.objects.create(
            user=user, folder=folder, name="Alpha Client"
        )
        Transaction.objects.create(
            contact=contact_b,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("500.00"),
        )
        Transaction.objects.create(
            contact=contact_a,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("500.00"),
        )
        result = get_clients_asymmetric()
        assert result[0]["name"] == "Alpha Client"
        assert result[1]["name"] == "Zebra Client"

    def test_empty_when_no_transactions(self):
        result = get_clients_asymmetric()
        assert result == []


# -----------------------------------------------------------
# get_client_history
# -----------------------------------------------------------
class TestGetClientHistory:
    def test_returns_transactions_ordered_by_date_then_id(self, contact):
        t1 = Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("500.00"),
        )
        t2 = Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Withdrawal",
            amount=Decimal("100.00"),
        )
        t3 = Transaction.objects.create(
            contact=contact,
            date="2024-01-02",
            type="Deposit",
            amount=Decimal("200.00"),
        )
        result = list(get_client_history(contact.id))
        assert result == [t1, t2, t3]

    def test_empty_for_client_with_no_transactions(self, contact):
        result = list(get_client_history(contact.id))
        assert result == []

    def test_only_returns_transactions_for_given_client(self, contact, folder, user):
        from apps.contacts.models import Contact

        other = Contact.objects.create(user=user, folder=folder, name="Other Client")
        Transaction.objects.create(
            contact=contact,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("500.00"),
        )
        Transaction.objects.create(
            contact=other,
            date="2024-01-01",
            type="Deposit",
            amount=Decimal("999.00"),
        )
        result = list(get_client_history(contact.id))
        assert len(result) == 1
        assert result[0].amount == Decimal("500.00")


# -----------------------------------------------------------
# get_account_history
# -----------------------------------------------------------
class TestGetAccountHistory:
    def test_30days_default(self, contact):
        today = date.today()
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=10),
            type="Deposit",
            amount=Decimal("100.00"),
        )
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=45),
            type="Deposit",
            amount=Decimal("200.00"),
        )
        result = list(get_account_history("30days"))
        assert len(result) == 1

    def test_60days(self, contact):
        today = date.today()
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=10),
            type="Deposit",
            amount=Decimal("100.00"),
        )
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=45),
            type="Deposit",
            amount=Decimal("200.00"),
        )
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=90),
            type="Deposit",
            amount=Decimal("300.00"),
        )
        result = list(get_account_history("60days"))
        assert len(result) == 2

    def test_all(self, contact):
        today = date.today()
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=10),
            type="Deposit",
            amount=Decimal("100.00"),
        )
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=365),
            type="Deposit",
            amount=Decimal("200.00"),
        )
        result = list(get_account_history("all"))
        assert len(result) == 2

    def test_ordered_newest_first(self, contact):
        today = date.today()
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=5),
            type="Deposit",
            amount=Decimal("100.00"),
            description="Newer",
        )
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=15),
            type="Deposit",
            amount=Decimal("200.00"),
            description="Older",
        )
        result = list(get_account_history("30days"))
        assert result[0].description == "Newer"
        assert result[1].description == "Older"

    def test_unknown_interval_defaults_to_30days(self, contact):
        today = date.today()
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=10),
            type="Deposit",
            amount=Decimal("100.00"),
        )
        Transaction.objects.create(
            contact=contact,
            date=today - timedelta(days=45),
            type="Deposit",
            amount=Decimal("200.00"),
        )
        result = list(get_account_history("bogus"))
        assert len(result) == 1
