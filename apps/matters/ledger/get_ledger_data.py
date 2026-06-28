from operator import itemgetter

from django.db.models import Sum

from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.invoices.models import Invoice


def get_ledger_data(matter):
    """Build the matter ledger.

    ``balance_due`` is the full running balance and INCLUDES deferred invoices.

    Deferred-fee arrangements (invoices manually marked ``DEFERRED``) are also
    broken out so the ledger can distinguish the accumulated recovery claim from
    what the client owes right now, and so trust clearance is not dragged down by
    fees the client is not currently obligated to pay:

    - ``deferred_total``   -- net recovery claim: sum of ``amount_remaining`` over
      ``DEFERRED`` invoices (i.e. after the client's payments/credits applied to them).
    - ``currently_owed``   -- sum of ``amount_remaining`` over non-deferred displayed
      invoices: what the client owes now. Used for the trust-clearance figure.
    - ``has_deferred``     -- whether this matter has any deferred recovery claim.

    When payments/credits are fully applied to invoices,
    ``currently_owed + deferred_total`` reconciles to ``balance_due``.
    """
    transactions = []
    balance = 0  # Initialize balance to prevent UnboundLocalError
    deferred_total = 0
    currently_owed = 0

    # Only include invoices that should be displayed in ledger (exclude DRAFT and APPROVED)
    invoices = (
        Invoice.objects.filter(matter=matter)
        .exclude(status__in=["DRAFT", "APPROVED"])
        .order_by("date_issued")
        or None
    )
    # Payments/credits on a matter's ledger are the amounts APPLIED to this
    # matter's invoices (payments are client-scoped now — unapplied funds are a
    # client-level credit, not part of this matter's ledger). One row per
    # payment/credit, carrying the total it applied here.
    payment_rows = list(
        PaymentApplication.objects.filter(invoice__matter=matter)
        .values("payment_id", "payment__date", "payment__payment_method")
        .annotate(applied=Sum("amount_applied"))
        .order_by("payment__date")
    )
    credit_rows = list(
        CreditApplication.objects.filter(invoice__matter=matter)
        .values("credit_id", "credit__date", "credit__detail")
        .annotate(applied=Sum("amount_applied"))
        .order_by("credit__date")
    )

    # Add invoices to transactions (exclude DRAFT and APPROVED)
    if invoices:
        for invoice in invoices:
            affects_balance = invoice.status not in [
                "DRAFT",
                "APPROVED",
                "VOID",
                "UNCOLLECTIBLE",
            ]
            is_deferred = invoice.status == "DEFERRED"
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date_issued,
                "transaction_type": "Charge",
                "description": f"Invoice {invoice.id}",
                "amount": invoice.value["final_total"],
                "invoice_status": invoice.status,
                "is_deferred": is_deferred,
                "affects_balance": affects_balance,
            }
            transactions.append(invoice_dict)

            # Break out the deferred recovery claim vs. what is currently owed,
            # netting payments/credits already applied to each invoice.
            if is_deferred:
                deferred_total += invoice.amount_remaining
            else:
                currently_owed += invoice.amount_remaining

    for row in payment_rows:
        transactions.append(
            {
                "id": row["payment_id"],
                "date": row["payment__date"],
                "transaction_type": "Credit",
                "description": f"Payment by {row['payment__payment_method'].lower()}",
                "amount": row["applied"],
                "affects_balance": True,  # Payments always affect balance
            }
        )

    for row in credit_rows:
        transactions.append(
            {
                "id": row["credit_id"],
                "date": row["credit__date"],
                "transaction_type": "Credit",
                "description": row["credit__detail"],
                "amount": row["applied"],
                "affects_balance": True,  # Credits always affect balance
            }
        )

    if transactions:
        transactions = sorted(transactions, key=itemgetter("transaction_type"))
        transactions = sorted(transactions, key=itemgetter("date"))

        # Calculate balance for each transaction (only counting those that affect balance)
        balance = 0
        for transaction in transactions:
            if transaction.get(
                "affects_balance", True
            ):  # Default to True for backwards compatibility
                if transaction["transaction_type"] == "Charge":
                    balance += transaction["amount"]
                else:
                    balance -= transaction["amount"]
            transaction["balance"] = balance

    # Calculate total credits (applied to this matter's invoices)
    total_credits = sum(row["applied"] for row in credit_rows)

    return {
        "transactions": transactions,
        "balance_due": balance,
        "deferred_total": deferred_total,
        "currently_owed": currently_owed,
        "has_deferred": bool(deferred_total),
        "total_credits": total_credits,
    }


def compute_trust_clearance(matter, client_trust_balance, currently_owed):
    """Trust funds free of current obligations: the confirmed client trust
    balance, less what's currently owed and less unbilled work.

    On a deferred-fee matter the unbilled fees accrue but are not currently
    collectible (the retainer is waived), so they must not drag clearance down —
    mirroring how ``currently_owed`` already excludes DEFERRED invoices. Shared
    by the matter ledger and the time-entry form so the figure can't diverge.
    """
    clearance = float(client_trust_balance) - float(currently_owed)
    if not matter.deferred_fees:
        clearance -= float(matter.value["unbilled"]["net_fees_and_expenses"])
    return clearance
