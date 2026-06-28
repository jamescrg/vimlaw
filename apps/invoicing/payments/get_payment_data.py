from decimal import Decimal

from django.db.models import DecimalField, F, Sum
from django.db.models.functions import Coalesce

from apps.invoicing.payments.filters import PaymentFilter
from apps.invoicing.payments.models import Payment
from apps.management.pagination import CustomPaginator


def get_payment_data(request):
    filter_data = request.session.get("payments_filter", {})

    if filter_data:
        filter = PaymentFilter(filter_data)
        payments = filter.qs
    else:
        payments = (
            Payment.objects.all().select_related("client").order_by("-date", "-id")
        )

    # Applied / Unapplied is computed from PaymentApplication sums (amount vs the
    # amount applied), not a stored column, so annotate and filter on it here.
    # The default ("") shows all payments.
    selected_application = filter_data.get("applied", "")
    if selected_application in ("applied", "unapplied"):
        payments = payments.annotate(
            applied_total=Coalesce(
                Sum("applications__amount_applied"),
                Decimal("0"),
                output_field=DecimalField(),
            )
        )
        if selected_application == "applied":
            payments = payments.filter(applied_total__gte=F("amount"))
        else:
            payments = payments.filter(applied_total__lt=F("amount"))

    payments_total = sum(payment.amount for payment in payments)

    pagination = CustomPaginator(
        payments, per_page=10, request=request, session_key="payments_pagination"
    )

    # Get current order and strip leading '-' for comparison
    current_order = filter_data.get("order_by", "date") if filter_data else "date"
    current_order = current_order.lstrip("-")

    filter_active = bool(
        filter_data
        and any(
            v
            for k, v in filter_data.items()
            if k not in ("order_by", "applied") and v not in (None, "")
        )
    )

    context = {
        "pagination": pagination,
        "session_key": "payments_pagination",
        "trigger_key": "paymentsChanged",
        "objects": pagination.get_object_list(),
        "payments_total": payments_total,
        "current_order": current_order,
        "filter_active": filter_active,
        "selected_application": selected_application,
    }

    return context
