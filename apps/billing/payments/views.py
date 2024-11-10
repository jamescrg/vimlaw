from django.contrib.auth.decorators import login_required
from django.shortcuts import HttpResponse, get_object_or_404, render

from apps.billing.invoices.models import Invoice
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter

from .filters import PaymentFilter
from .forms import PaymentForm
from .models import Payment


@login_required
def payments_index(request):
    context = {
        "app": "billing",
        "subapp": "payments",
    }

    return render(request, "billing/payments/main.html", context)


@login_required
def payments_list(request):
    filter_data = request.session.get("payments_filter", None)

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
        "app": "billing",
        "subapp": "payments",
        "pagination": pagination,
        "session_key": "payments_pagination",
        "trigger_key": "paymentsChanged",
        "objects": pagination.get_object_list(),
        "payments_total": payments_total,
    }

    return render(request, "billing/payments/list.html", context)


@login_required
def payments_add(request):
    matters = Matter.objects.exclude(status="Closed").order_by("name")

    form = PaymentForm(request.POST or None, use_required_attribute=False)
    form.fields["matter"].queryset = matters

    if request.method == "POST" and form.is_valid():
        form.save()

        return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})

    return render(request, "billing/payments/form.html", {"form": form})


@login_required
def payments_delete(_, pk):
    Payment.objects.get(pk=pk).delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})


@login_required
def payments_edit(request, pk):
    payment = get_object_or_404(Payment, pk=pk)

    matter_ids = Invoice.objects.filter(status="SENT").values_list("matter", flat=True)
    matters = Matter.objects.filter(id__in=matter_ids) | Matter.objects.filter(
        id=payment.matter.id
    )

    if request.method == "POST":
        form = PaymentForm(request.POST, instance=payment, use_required_attribute=False)

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})
    else:
        form = PaymentForm(instance=payment, use_required_attribute=False)

    form.fields["matter"].queryset = matters

    return render(
        request,
        "billing/payments/edit.html",
        {"form": form, "payment": payment},
    )


@login_required
def payments_filter(request):
    def get_filter(request):
        filter_data = request.session.get("payments_filter", request.POST)

        return PaymentFilter(
            filter_data,
            queryset=Payment.objects.all()
            .select_related("matter")
            .order_by("-date", "-id"),
        )

    if request.method == "POST":
        request.session["payments_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})
    else:
        filter = get_filter(request)

        return render(request, "billing/payments/filter.html", {"filter": filter})


@login_required
def order_by_payments(request, order):
    filter_data = request.session.get("payments_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["payments_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})
