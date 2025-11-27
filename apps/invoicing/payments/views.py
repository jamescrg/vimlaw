import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import HttpResponse, get_object_or_404, render
from django.urls import reverse

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
def payments_apply(request, pk):
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
        from decimal import Decimal, InvalidOperation

        errors = []
        applications_to_create = []
        total_to_apply = Decimal("0")

        # Validate all applications before creating any
        for invoice_dict in invoice_data:
            invoice = invoice_dict["invoice"]
            amount_key = f"amount_{invoice.id}"
            amount_str = request.POST.get(amount_key, "").strip()

            if amount_str:
                try:
                    amount_applied = Decimal(amount_str)

                    if amount_applied <= 0:
                        errors.append(
                            f"Invoice #{invoice.id}: Amount must be greater than 0"
                        )
                        continue

                    # Check doesn't exceed invoice remaining
                    if amount_applied > invoice_dict["amount_remaining"]:
                        errors.append(
                            f"Invoice #{invoice.id}: Cannot apply ${amount_applied} "
                            f"(only ${invoice_dict['amount_remaining']} remaining)"
                        )
                        continue

                    total_to_apply += amount_applied
                    applications_to_create.append((invoice, amount_applied))

                except (InvalidOperation, ValueError):
                    errors.append(
                        f"Invoice #{invoice.id}: Invalid amount '{amount_str}'"
                    )

        # Check total doesn't exceed payment available
        if total_to_apply > payment.amount_unapplied:
            errors.append(
                f"Total application ${total_to_apply} exceeds "
                f"available payment amount ${payment.amount_unapplied}"
            )

        # If validation errors, return them
        if errors:
            existing_applications = list(
                PaymentApplication.objects.filter(payment=payment)
                .select_related("invoice")
                .order_by("created_at")
            )
            for app in existing_applications:
                app.delete_url = reverse(
                    "invoicing:payments-application-delete", args=[app.id]
                )
            context = {
                "source": payment,
                "source_type": "payment",
                "apply_url": reverse("invoicing:payments-apply", args=[payment.id]),
                "invoice_data": invoice_data,
                "amount_unapplied": payment.amount_unapplied,
                "existing_applications": existing_applications,
                "errors": errors,
            }
            return render(
                request, "invoicing/applications/apply.html", context, status=400
            )

        # Create applications and track affected invoices
        affected_invoices = set()
        for invoice, amount_applied in applications_to_create:
            PaymentApplication.objects.create(
                payment=payment, invoice=invoice, amount_applied=amount_applied
            )
            affected_invoices.add(invoice)

        # Auto-update invoice status if fully paid
        for invoice in affected_invoices:
            invoice.refresh_from_db()
            if invoice.amount_remaining == 0 and invoice.status != "PAID":
                invoice.status = "PAID"
                invoice.save()

        return HttpResponse(
            status=204,
            headers={
                "HX-Trigger": json.dumps(
                    {"paymentsChanged": "", "matterLedgerChanged": ""}
                )
            },
        )

    # Get existing applications for this payment
    existing_applications = list(
        PaymentApplication.objects.filter(payment=payment)
        .select_related("invoice")
        .order_by("created_at")
    )
    for app in existing_applications:
        app.delete_url = reverse("invoicing:payments-application-delete", args=[app.id])

    context = {
        "source": payment,
        "source_type": "payment",
        "apply_url": reverse("invoicing:payments-apply", args=[payment.id]),
        "invoice_data": invoice_data,
        "amount_unapplied": payment.amount_unapplied,
        "existing_applications": existing_applications,
    }

    return render(request, "invoicing/applications/apply.html", context)


@login_required
def payments_delete_application(request, pk):
    """Delete a payment application and update invoice status if needed."""
    application = get_object_or_404(PaymentApplication, pk=pk)
    payment = application.payment

    # Delete will trigger the model's delete() method which handles invoice status
    application.delete()

    # Get updated data for the modal
    unpaid_invoices = (
        Invoice.objects.filter(matter=payment.matter, status="SENT")
        .select_related("matter")
        .order_by("date_issued")
    )

    invoice_data = []
    for invoice in unpaid_invoices:
        remaining = invoice.amount_remaining
        if remaining > 0:
            invoice_data.append({"invoice": invoice, "amount_remaining": remaining})

    existing_applications = list(
        PaymentApplication.objects.filter(payment=payment)
        .select_related("invoice")
        .order_by("created_at")
    )
    for app in existing_applications:
        app.delete_url = reverse("invoicing:payments-application-delete", args=[app.id])

    context = {
        "source": payment,
        "source_type": "payment",
        "apply_url": reverse("invoicing:payments-apply", args=[payment.id]),
        "invoice_data": invoice_data,
        "amount_unapplied": payment.amount_unapplied,
        "existing_applications": existing_applications,
    }

    response = render(request, "invoicing/applications/apply.html", context)
    response["HX-Trigger"] = json.dumps(
        {"paymentsChanged": "", "matterLedgerChanged": ""}
    )
    return response


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
