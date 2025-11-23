import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import HttpResponse, get_object_or_404, render

from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.get_payment_data import get_payment_data
from apps.matters.models import Matter

from .filters import PaymentFilter
from .forms import PaymentForm
from .models import Payment


@login_required
def payments_index(request):
    payment_data = get_payment_data(request)

    context = {
        "app": "invoicing",
        "subapp": "payments",
    } | payment_data

    return render(request, "invoicing/payments/main.html", context)


@login_required
def payments_list(request):
    payment_data = get_payment_data(request)

    context = {
        "app": "invoicing",
        "subapp": "payments",
    }

    context = context | payment_data

    return render(request, "invoicing/payments/list.html", context)


@login_required
def payments_add(request):
    matters = Matter.objects.exclude(status__in=["Pending", "Closed"]).order_by("name")

    form = PaymentForm(request.POST or None, use_required_attribute=False)
    form.fields["matter"].queryset = matters

    if request.method == "POST" and form.is_valid():
        form.save()

        return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})

    return render(request, "invoicing/payments/form.html", {"form": form})


@login_required
def payments_delete(_, pk):
    Payment.objects.get(pk=pk).delete()

    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"paymentsChanged": "", "matterLedgerChanged": ""})
        },
    )


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

            return HttpResponse(
                status=204,
                headers={
                    "HX-Trigger": json.dumps(
                        {"paymentsChanged": "", "matterLedgerChanged": ""}
                    )
                },
            )
    else:
        form = PaymentForm(instance=payment, use_required_attribute=False)

    form.fields["matter"].queryset = matters

    return render(
        request,
        "invoicing/payments/edit.html",
        {"form": form, "payment": payment},
    )


@login_required
def payments_allocate(request, pk):
    payment = get_object_or_404(Payment, pk=pk)

    # Get unpaid invoices for this payment's matter
    unpaid_invoices = (
        Invoice.objects.filter(matter=payment.matter, status="SENT")
        .select_related("matter")
        .order_by("date_issued")
    )

    # Build list with amount_remaining for each invoice
    invoice_data = []
    for invoice in unpaid_invoices:
        remaining = invoice.amount_remaining
        if remaining > 0:
            invoice_data.append({"invoice": invoice, "amount_remaining": remaining})

    if request.method == "POST":
        # Create PaymentApplication records from form data
        for invoice_dict in invoice_data:
            invoice = invoice_dict["invoice"]
            amount_key = f"amount_{invoice.id}"
            amount_applied = request.POST.get(amount_key)

            if amount_applied and float(amount_applied) > 0:
                PaymentApplication.objects.create(
                    payment=payment, invoice=invoice, amount_applied=amount_applied
                )

        return HttpResponse(
            status=204,
            headers={
                "HX-Trigger": json.dumps(
                    {"paymentsChanged": "", "matterLedgerChanged": ""}
                )
            },
        )

    context = {
        "payment": payment,
        "invoice_data": invoice_data,
        "amount_unallocated": payment.amount_unallocated,
    }

    return render(request, "invoicing/payments/allocate.html", context)


@login_required
def payments_filter(request):
    def get_filter(request):
        filter_data = request.session.get("payments_filter", request.POST)

        if filter_data:
            return PaymentFilter(
                filter_data,
                queryset=Payment.objects.all()
                .select_related("matter")
                .order_by("-date", "-id"),
            )
        else:
            default_filter = {"order_by": "-date"}

        return PaymentFilter(
            default_filter,
            queryset=Payment.objects.all()
            .select_related("matter")
            .order_by("-date", "-id"),
        )

    if request.method == "POST":
        request.session["payments_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "paymentsChanged"})
    else:
        filter = get_filter(request)

        return render(request, "invoicing/payments/filter.html", {"filter": filter})


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
