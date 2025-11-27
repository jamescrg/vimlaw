import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.invoicing.applications.models import CreditApplication
from apps.invoicing.credits.filters import CreditsFilter
from apps.invoicing.credits.forms import CreditsForm
from apps.invoicing.credits.get_credits_data import get_credits_data
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.matters.models import Matter


@login_required
def credits_index(request):
    credits_data = get_credits_data(request)

    context = {
        "app": "invoicing",
        "subapp": "credits",
    } | credits_data

    return render(request, "invoicing/credits/main.html", context)


@login_required
def credits_list(request):
    credits_data = get_credits_data(request)

    context = {
        "app": "invoicing",
        "subapp": "credits",
    } | credits_data

    return render(request, "invoicing/credits/list.html", context)


@login_required
def credits_add(request):
    matters = Matter.objects.exclude(status__in=["Pending", "Closed"]).order_by("name")

    form = CreditsForm(request.POST or None, use_required_attribute=False)
    form.fields["matter"].queryset = matters

    if request.method == "POST" and form.is_valid():
        form.save()

        return HttpResponse(status=204, headers={"HX-Trigger": "creditsChanged"})

    return render(request, "invoicing/credits/form.html", {"form": form})


@login_required
def credits_edit(request, pk):
    credit = get_object_or_404(Credit, pk=pk)

    matters = Matter.objects.exclude(status__in=["Pending", "Closed"]).order_by("name")

    if request.method == "POST":
        form = CreditsForm(request.POST, instance=credit, use_required_attribute=False)

        if form.is_valid():
            form.save()

            return HttpResponse(
                status=204,
                headers={
                    "HX-Trigger": json.dumps(
                        {"creditsChanged": "", "matterLedgerChanged": ""}
                    )
                },
            )
    else:
        form = CreditsForm(instance=credit, use_required_attribute=False)

    form.fields["matter"].queryset = matters

    return render(
        request, "invoicing/credits/edit.html", {"form": form, "credit": credit}
    )


@login_required
def credits_delete(_, pk):
    Credit.objects.get(pk=pk).delete()

    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"creditsChanged": "", "matterLedgerChanged": ""})
        },
    )


@login_required
def order_by_credits(request, order):
    filter_data = request.session.get("credits_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["credits_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "creditsChanged"})


@login_required
def credits_filter(request):
    def get_filter(request):
        filter_data = request.session.get("credits_filter", request.POST)

        if filter_data:
            return CreditsFilter(
                filter_data,
                queryset=Credit.objects.all()
                .select_related("matter")
                .order_by("-date", "-id"),
            )
        else:
            default_filter = {"order_by": "-date"}

        return CreditsFilter(
            default_filter,
            queryset=Credit.objects.all()
            .select_related("matter")
            .order_by("-date", "-id"),
        )

    if request.method == "POST":
        request.session["credits_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "creditsChanged"})
    else:
        filter = get_filter(request)

        return render(request, "invoicing/credits/filter.html", {"filter": filter})


@login_required
def credits_apply(request, pk):
    credit = get_object_or_404(Credit, pk=pk)

    # Get unpaid invoices for this credit's matter
    unpaid_invoices = (
        Invoice.objects.filter(matter=credit.matter, status="SENT")
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

        # Check total doesn't exceed credit available
        if total_to_apply > credit.amount_unapplied:
            errors.append(
                f"Total application ${total_to_apply} exceeds "
                f"available credit amount ${credit.amount_unapplied}"
            )

        # If validation errors, return them
        if errors:
            existing_applications = list(
                CreditApplication.objects.filter(credit=credit)
                .select_related("invoice")
                .order_by("created_at")
            )
            for app in existing_applications:
                app.delete_url = reverse(
                    "invoicing:credits-application-delete", args=[app.id]
                )
            context = {
                "source": credit,
                "source_type": "credit",
                "apply_url": reverse("invoicing:credits-apply", args=[credit.id]),
                "invoice_data": invoice_data,
                "amount_unapplied": credit.amount_unapplied,
                "existing_applications": existing_applications,
                "errors": errors,
            }
            return render(
                request, "invoicing/applications/apply.html", context, status=400
            )

        # Create applications and track affected invoices
        affected_invoices = set()
        for invoice, amount_applied in applications_to_create:
            CreditApplication.objects.create(
                credit=credit, invoice=invoice, amount_applied=amount_applied
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
                    {"creditsChanged": "", "matterLedgerChanged": ""}
                )
            },
        )

    # Get existing applications for this credit
    existing_applications = list(
        CreditApplication.objects.filter(credit=credit)
        .select_related("invoice")
        .order_by("created_at")
    )
    for app in existing_applications:
        app.delete_url = reverse("invoicing:credits-application-delete", args=[app.id])

    context = {
        "source": credit,
        "source_type": "credit",
        "apply_url": reverse("invoicing:credits-apply", args=[credit.id]),
        "invoice_data": invoice_data,
        "amount_unapplied": credit.amount_unapplied,
        "existing_applications": existing_applications,
    }

    return render(request, "invoicing/applications/apply.html", context)


@login_required
def credits_delete_application(request, pk):
    """Delete a credit application and update invoice status if needed."""
    application = get_object_or_404(CreditApplication, pk=pk)
    credit = application.credit

    # Delete will trigger the model's delete() method which handles invoice status
    application.delete()

    # Get updated data for the modal
    unpaid_invoices = (
        Invoice.objects.filter(matter=credit.matter, status="SENT")
        .select_related("matter")
        .order_by("date_issued")
    )

    invoice_data = []
    for invoice in unpaid_invoices:
        remaining = invoice.amount_remaining
        if remaining > 0:
            invoice_data.append({"invoice": invoice, "amount_remaining": remaining})

    existing_applications = list(
        CreditApplication.objects.filter(credit=credit)
        .select_related("invoice")
        .order_by("created_at")
    )
    for app in existing_applications:
        app.delete_url = reverse("invoicing:credits-application-delete", args=[app.id])

    context = {
        "source": credit,
        "source_type": "credit",
        "apply_url": reverse("invoicing:credits-apply", args=[credit.id]),
        "invoice_data": invoice_data,
        "amount_unapplied": credit.amount_unapplied,
        "existing_applications": existing_applications,
    }

    response = render(request, "invoicing/applications/apply.html", context)
    response["HX-Trigger"] = json.dumps(
        {"creditsChanged": "", "matterLedgerChanged": ""}
    )
    return response
