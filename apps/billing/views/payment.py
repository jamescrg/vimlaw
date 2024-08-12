from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.billing.filters.payment import PaymentFilter
from apps.billing.forms.payment import PaymentForm
from apps.billing.models.invoice import Invoice
from apps.billing.models.payment import Payment
from apps.matters.models import Matter


@login_required
def add_payment(request):
    if request.method == "POST":
        form = PaymentForm(request.POST)

        if form.is_valid():
            payment = form.save(commit=False)
            payment.save()

            return redirect("billing:billing")
    else:
        form = PaymentForm()

        matter_ids = (
            Invoice.objects.filter(status="SENT")
            .select_related("matter")
            .values_list("matter", flat=True)
        )

        matters = Matter.objects.filter(id__in=matter_ids)
        form.fields["matter"].queryset = matters

    return render(request, "billing/payments/form-payment.html", {"form": form})


@login_required
def delete_payment(request, pk):
    payment = Payment.objects.get(pk=pk)
    payment.delete()

    payments = Payment.objects.all().select_related("matter")

    return render(request, "billing/payments/payment-list.html", {"payments": payments})


@login_required
def edit_payment(request, pk):
    payment = Payment.objects.get(pk=pk)

    if request.method == "POST":
        form = PaymentForm(request.POST, instance=payment)

        if form.is_valid():
            form.save()

            return redirect("billing:billing")
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
        "billing/payments/edit-payment.html",
        {"form": form, "payment": payment},
    )


@login_required
def payment_filter(request):
    def get_filter(request):
        filter_data = request.session.get("payment_filter", request.POST)

        return PaymentFilter(
            filter_data, queryset=Payment.objects.all().select_related("matter")
        )

    if request.method == "POST":
        request.session["payment_filter"] = request.POST

        return redirect("billing:billing")
    else:
        filter = get_filter(request)

        return render(
            request, "billing/payments/payment-filter.html", {"filter": filter}
        )
