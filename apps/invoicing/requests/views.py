from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.invoicing.pay.balance import matter_balance_cents
from apps.invoicing.requests.forms import PaymentRequestForm
from apps.invoicing.requests.models import PaymentRequest
from apps.invoicing.requests.send import (
    PaymentRequestSendError,
    send_payment_request,
)
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from utils.toasts import toast_success


def _requests_context(request):
    requests = PaymentRequest.objects.select_related("matter", "payment").order_by(
        "-created_at"
    )
    pagination = CustomPaginator(
        requests, per_page=10, request=request, session_key="requests_pagination"
    )
    return {
        "app": "invoicing",
        "subapp": "requests",
        "pagination": pagination,
        "session_key": "requests_pagination",
        "trigger_key": "requestsChanged",
        "objects": pagination.get_object_list(),
    }


@login_required
def requests_index(request):
    return render(request, "invoicing/requests/main.html", _requests_context(request))


@login_required
def requests_list(request):
    return render(request, "invoicing/requests/list.html", _requests_context(request))


@login_required
def requests_new(request):
    """Create a payment request: snapshot the matter's full open balance and
    record it (SENT). Emailing the link + ledger statement comes in phase 4."""
    matters = Matter.objects.exclude(status__in=["Pending", "Closed"]).order_by("name")
    form = PaymentRequestForm(request.POST or None, use_required_attribute=False)
    form.fields["matter"].queryset = matters

    if request.method == "POST" and form.is_valid():
        payment_request = form.save(commit=False)
        balance_cents = matter_balance_cents(payment_request.matter)
        if balance_cents <= 0:
            form.add_error("matter", "This matter has no open balance to request.")
        else:
            payment_request.amount_requested = Decimal(balance_cents) / 100
            payment_request.status = "SENT"
            # Persist + send together: if the email fails, roll back so we never
            # leave an unsent request behind.
            try:
                with transaction.atomic():
                    payment_request.save()
                    send_payment_request(payment_request, request=request)
            except PaymentRequestSendError as exc:
                form.add_error(None, str(exc))
            else:
                response = HttpResponse(
                    status=204, headers={"HX-Trigger": "requestsChanged"}
                )
                toast_success(
                    response,
                    f"Payment request sent to {payment_request.recipient_email}.",
                )
                return response

    return render(request, "invoicing/requests/form.html", {"form": form})


@login_required
def requests_cancel(request, pk):
    payment_request = get_object_or_404(PaymentRequest, pk=pk)
    if payment_request.status == "SENT":
        payment_request.status = "CANCELED"
        payment_request.save(update_fields=["status"])
    return render(
        request, "invoicing/requests/row.html", {"payment_request": payment_request}
    )
