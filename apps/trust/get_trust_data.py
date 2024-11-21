import apps.trust.trust as trust
from apps.management.pagination import CustomPaginator


def get_trust_data(request):
    contacts = trust.get_clients_asymmetric()
    contacts = trust.get_pending_client_balances(contacts)
    contacts = trust.get_confirmed_client_balances(contacts)

    pending_account_balance = trust.get_pending_account_balance()
    confirmed_account_balance = trust.get_confirmed_account_balance()

    pagination = CustomPaginator(
        contacts, per_page=50, request=request, session_key="trust_pagination"
    )

    context = {
        "pagination": pagination,
        "contacts": pagination.get_object_list(),
        "session_key": "trust_pagination",
        "trigger_key": "trustChanged",
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
    }

    return context
