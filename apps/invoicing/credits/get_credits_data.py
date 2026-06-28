from decimal import Decimal

from django.db.models import DecimalField, F, Sum
from django.db.models.functions import Coalesce

from apps.invoicing.credits.filters import CreditsFilter
from apps.invoicing.credits.models import Credit
from apps.management.pagination import CustomPaginator


def get_credits_data(request):
    filter_data = request.session.get("credits_filter", {})

    if filter_data:
        filter = CreditsFilter(filter_data)
        credits = filter.qs
    else:
        credits = Credit.objects.all().select_related("client").order_by("-date", "-id")

    # Applied / Unapplied is computed from CreditApplication sums (amount vs the
    # amount applied), not a stored column, so annotate and filter on it here.
    # The default ("") shows all credits.
    selected_application = filter_data.get("applied", "")
    if selected_application in ("applied", "unapplied"):
        credits = credits.annotate(
            applied_total=Coalesce(
                Sum("applications__amount_applied"),
                Decimal("0"),
                output_field=DecimalField(),
            )
        )
        if selected_application == "applied":
            credits = credits.filter(applied_total__gte=F("amount"))
        else:
            credits = credits.filter(applied_total__lt=F("amount"))

    pagination = CustomPaginator(
        credits, per_page=10, request=request, session_key="credits_pagination"
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
        "session_key": "credits_pagination",
        "trigger_key": "creditsChanged",
        "objects": pagination.get_object_list(),
        "current_order": current_order,
        "filter_active": filter_active,
        "selected_application": selected_application,
    }

    return context
