from apps.billing.payments.filters import PaymentFilter
from apps.billing.payments.models import Payment
from apps.management.pagination import CustomPaginator


def get_payment_data(request):
    filter_data = request.session.get("payments_filter", {})

    if filter_data:
        filter = PaymentFilter(filter_data)
        payments = filter.qs
    else:
        payments = (
            Payment.objects.all().select_related("matter").order_by("-date", "-id")
        )

    payments_total = sum(payment.amount for payment in payments)

    pagination = CustomPaginator(
        payments, per_page=10, request=request, session_key="payments_pagination"
    )

    context = {
        "pagination": pagination,
        "session_key": "payments_pagination",
        "trigger_key": "paymentsChanged",
        "objects": pagination.get_object_list(),
        "payments_total": payments_total,
    }

    return context
