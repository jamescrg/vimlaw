"""Trust available — the single authority for the whole app.

A client's trust is one pooled balance that ALL their matters draw on, so
trust available is inherently **client-level**:

    trust_available(client) = PENDING trust balance
                            − currently owed across the client's non-deferred
                              invoices
                            − unbilled net fees/expenses on the client's
                              non-deferred-fee matters

**Pending, not confirmed:** firms customarily work against provisional deposits
in the expectation they'll clear (the lost opportunity of waiting outweighs the
small chance of a loss). A **matter's** trust available is simply its client's —
the pool is shared — so per-matter callers use ``client_trust_available``.

Entry points:
- ``trust_available_by_client(ids)`` → ``{client_id: Decimal}`` in a handful of
  bulk queries (for the Account Summary and the dashboard's matter list);
- ``client_trust_available(id)`` → the single-client figure (matter ledger,
  matter detail, the time-entry form);
- ``attach_client_trust_available(rows)`` → sets ``row["trust_available"]`` on
  Summary dicts.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

_DEC = DecimalField(max_digits=14, decimal_places=2)
_ZERO = Decimal("0")


def _coalesced_sum(queryset, group_field, expr):
    """A correlated per-parent ``Sum`` subquery, 0 when there are no rows.

    ``queryset`` is already filtered to ``<group_field>=OuterRef("pk")``; grouping
    by that field yields a single row (the sum for the outer object).
    """
    return Coalesce(
        Subquery(
            queryset.values(group_field)
            .annotate(total=Sum(expr, output_field=_DEC))
            .values("total"),
            output_field=_DEC,
        ),
        0,
        output_field=_DEC,
    )


def _pending_balance_by_client(client_ids):
    """``{client_id: pending trust balance}`` — deposits minus withdrawals across
    ALL confirmation states (the bulk form of trust.get_pending_client_balance)."""
    from apps.trust.models import Transaction

    rows = (
        Transaction.objects.filter(contact_id__in=client_ids)
        .values("contact_id")
        .annotate(
            bal=Sum(
                Case(
                    When(type="Deposit", then=F("amount")),
                    When(type="Withdrawal", then=-F("amount")),
                    default=Value(_ZERO),
                    output_field=_DEC,
                ),
                output_field=_DEC,
            )
        )
    )
    return {r["contact_id"]: (r["bal"] or _ZERO) for r in rows}


def _owed_by_client(client_ids):
    """``{client_id: currently owed}`` across the client's DISPLAYED, non-deferred
    invoices. Reproduces Invoice.amount_remaining (which has Python-only branches
    for VOID/UNCOLLECTIBLE and legacy PAID-without-allocations), so we bulk-
    annotate the components and finish the arithmetic in Python."""
    from apps.activity.expenses.models import ExpenseEntry
    from apps.activity.flat_fees.models import FlatFeeEntry
    from apps.activity.time.models import TimeEntry
    from apps.invoicing.applications.models import (
        CreditApplication,
        PaymentApplication,
    )
    from apps.invoicing.invoices.models import Invoice

    fee = F("hours") * F("rate")  # time-entry fee = hours × rate
    invoices = (
        Invoice.objects.filter(matter__client_id__in=client_ids)
        .exclude(status__in=["DRAFT", "APPROVED"])
        .annotate(
            net_fees=_coalesced_sum(
                TimeEntry.objects.filter(invoice=OuterRef("pk")).exclude(comp=True),
                "invoice",
                fee,
            ),
            net_exp=_coalesced_sum(
                ExpenseEntry.objects.filter(invoice=OuterRef("pk")).exclude(comp=True),
                "invoice",
                F("amount"),
            ),
            net_flat=_coalesced_sum(
                FlatFeeEntry.objects.filter(invoice=OuterRef("pk")).exclude(comp=True),
                "invoice",
                F("amount"),
            ),
            pay=_coalesced_sum(
                PaymentApplication.objects.filter(invoice=OuterRef("pk")),
                "invoice",
                F("amount_applied"),
            ),
            cred=_coalesced_sum(
                CreditApplication.objects.filter(invoice=OuterRef("pk")),
                "invoice",
                F("amount_applied"),
            ),
        )
        .values(
            "matter__client_id",
            "status",
            "discount",
            "net_fees",
            "net_exp",
            "net_flat",
            "pay",
            "cred",
        )
    )
    owed = defaultdict(Decimal)
    for inv in invoices:
        status = inv["status"]
        if status == "DEFERRED":
            continue  # deferred recovery claim, not currently owed
        if status in ("VOID", "UNCOLLECTIBLE"):
            remaining = _ZERO
        else:
            final_total = (
                inv["net_fees"]
                + inv["net_exp"]
                + inv["net_flat"]
                - (inv["discount"] or _ZERO)
            )
            if status == "PAID" and inv["pay"] == 0 and inv["cred"] == 0:
                remaining = _ZERO  # legacy PAID without allocations
            else:
                remaining = final_total - inv["pay"] - inv["cred"]
        owed[inv["matter__client_id"]] += remaining
    return owed


def _unbilled_by_client(client_ids):
    """``{client_id: unbilled net fees/expenses}`` — sum of each non-deferred-fee
    matter's unbilled net work (deferred-fee matters accrue but aren't
    collectible, so they must not drag trust available down)."""
    from apps.activity.expenses.models import ExpenseEntry
    from apps.activity.flat_fees.models import FlatFeeEntry
    from apps.activity.time.models import TimeEntry
    from apps.matters.models import Matter

    fee = F("hours") * F("rate")
    matters = (
        Matter.objects.filter(client_id__in=client_ids, deferred_fees=False)
        .annotate(
            net_fees=_coalesced_sum(
                TimeEntry.objects.filter(
                    matter=OuterRef("pk"), entered=False, invoice__isnull=True
                ).exclude(comp=True),
                "matter",
                fee,
            ),
            net_exp=_coalesced_sum(
                ExpenseEntry.objects.filter(
                    matter=OuterRef("pk"), entered=False, invoice__isnull=True
                ).exclude(comp=True),
                "matter",
                F("amount"),
            ),
            net_flat=_coalesced_sum(
                FlatFeeEntry.objects.filter(
                    matter=OuterRef("pk"), entered=False, invoice__isnull=True
                ).exclude(comp=True),
                "matter",
                F("amount"),
            ),
        )
        .values("client_id", "net_fees", "net_exp", "net_flat")
    )
    unbilled = defaultdict(Decimal)
    for m in matters:
        unbilled[m["client_id"]] += m["net_fees"] + m["net_exp"] + m["net_flat"]
    return unbilled


def trust_available_by_client(client_ids):
    """``{client_id: Decimal}`` trust available — see the module docstring. Bulk:
    a handful of queries total, not one per client."""
    client_ids = list(client_ids)
    if not client_ids:
        return {}
    balance = _pending_balance_by_client(client_ids)
    owed = _owed_by_client(client_ids)
    unbilled = _unbilled_by_client(client_ids)
    return {
        cid: balance.get(cid, _ZERO) - owed.get(cid, _ZERO) - unbilled.get(cid, _ZERO)
        for cid in client_ids
    }


def client_trust_available(client_id):
    """A single client's trust available (Decimal). A matter's trust available
    is its client's — the pooled trust is shared — so per-matter callers pass
    ``matter.client_id`` here. Returns 0 for a matter with no client."""
    if client_id is None:
        return _ZERO
    return trust_available_by_client([client_id]).get(client_id, _ZERO)


def attach_client_trust_available(contacts):
    """Set ``contact["trust_available"]`` (Decimal) on each Account Summary row
    dict, from the one authoritative calculation. Returns the same list."""
    available_by_client = trust_available_by_client([c["id"] for c in contacts])
    for c in contacts:
        c["trust_available"] = available_by_client.get(c["id"], _ZERO)
    return contacts
