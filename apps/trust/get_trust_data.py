from decimal import Decimal

import apps.trust.trust as trust
from apps.management.pagination import CustomPaginator
from apps.trust.available import attach_client_trust_available

# Row-dict keys the summary table can be sorted by (via trust:order-by).
_SORT_KEYS = {
    "name",
    "pending_client_balance",
    "confirmed_client_balance",
    "trust_available",
}


def get_trust_data(request):
    contacts = trust.get_clients_asymmetric()
    contacts = trust.get_pending_client_balances(contacts)
    contacts = trust.get_confirmed_client_balances(contacts)
    contacts = attach_client_trust_available(contacts)

    # Session-backed sort (toggled by the header buttons via trust:order-by),
    # applied to the full list before pagination so it sorts across pages. A
    # leading '-' means descending; default is client name ascending.
    order = request.session.get("trust_order", "name")
    key = order.lstrip("-")
    if key not in _SORT_KEYS:
        key, order = "name", "name"
    reverse = order.startswith("-")
    if key == "name":
        contacts.sort(key=lambda c: (c["name"] or "").lower(), reverse=reverse)
    else:
        contacts.sort(key=lambda c: c.get(key) or 0, reverse=reverse)

    total_trust_available = sum((c["trust_available"] for c in contacts), Decimal("0"))
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
        "current_order": key,
        "pending_account_balance": pending_account_balance,
        "confirmed_account_balance": confirmed_account_balance,
        "total_trust_available": total_trust_available,
    }

    return context
