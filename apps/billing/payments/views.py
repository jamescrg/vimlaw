from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.billing.invoices.models import Invoice
from apps.matters.models import Matter

from .filters import PaymentFilter
from .forms import PaymentForm
from .models import Payment


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

    page = request.GET.get("page")
    pagination = Paginator(payments, per_page=10).get_page(page)

    context = {
        "page": "billing",
        "subpage": "payments",
        "pagination": pagination,
        "objects": pagination.object_list,
    }

    return render(request, "billing/payments/list.html", context)


@login_required
def payments_add(request):
    if request.method == "POST":
        form = PaymentForm(request.POST)

        if form.is_valid():
            payment = form.save(commit=False)
            payment.save()

            return redirect("billing:payments-list")
    else:
        form = PaymentForm()

        matter_ids = (
            Invoice.objects.filter(status="SENT")
            .select_related("matter")
            .values_list("matter", flat=True)
        )

        matters = Matter.objects.filter(id__in=matter_ids).order_by("name")
        form.fields["matter"].queryset = matters

    return render(request, "billing/payments/form.html", {"form": form})


@login_required
def payments_delete(request, pk):
    payment = Payment.objects.get(pk=pk)
    payment.delete()
    return redirect("billing:payments-list")


@login_required
def payments_edit(request, pk):
    payment = Payment.objects.get(pk=pk)

    if request.method == "POST":
        form = PaymentForm(request.POST, instance=payment)

        if form.is_valid():
            form.save()

            return redirect("billing:payments-list")
    else:
        form = PaymentForm(instance=payment)

        matter_ids = Invoice.objects.filter(status="SENT").values_list(
            "matter", flat=True
        )

        matters = Matter.objects.filter(id__in=matter_ids) | Matter.objects.filter(
            id=payment.matter.id
        )

        form.fields["matter"].queryset = matters
        form.fields["matter"].initial = payment.matter
        form.fields["date"].initial = payment.date
        form.fields["amount"].initial = payment.amount
        form.fields["payment_method"].initial = payment.payment_method
        form.fields["detail"].initial = payment.detail

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
            filter_data, queryset=Payment.objects.all().select_related("matter")
        )

    if request.method == "POST":
        request.session["payments_filter"] = request.POST

        return redirect("billing:payments-list")
    else:
        filter = get_filter(request)

        return render(request, "billing/payments/filter.html", {"filter": filter})
