from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.billing.invoice_filters import InvoiceFilter
from apps.billing.invoice_models import Invoice
from apps.billing.payment_filters import PaymentFilter
from apps.billing.payment_models import Payment


@login_required
def billing_index(request):
    context = {}
    context["page"] = "billing"

    tab = request.session.get("billing_tab", "invoices")
    context["tab"] = tab

    if tab == "invoices":
        filter_data = request.session.get("invoice_filter", None)

        if filter_data:
            filter = InvoiceFilter(filter_data)
            invoices = filter.qs
        else:
            invoices = (
                Invoice.objects.all()
                .select_related("matter", "created_by")
                .order_by("-created_at")
            )

        context["invoices"] = invoices

    elif tab == "payments":
        filter_data = request.session.get("payment_filter", None)

        if filter_data:
            filter = PaymentFilter(filter_data)
            payments = filter.qs
        else:
            payments = Payment.objects.all().select_related("matter")

        context["payments"] = payments

    return render(request, "billing/billing-main.html", context)


@login_required
def set_tab(request, tab):
    request.session["billing_tab"] = tab
    request.session.modified = True

    return redirect("/billing")
