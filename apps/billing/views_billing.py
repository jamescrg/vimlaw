from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.billing.filters_invoice import InvoiceFilter
from apps.billing.filters_payment import PaymentFilter
from apps.billing.models_invoice import Invoice
from apps.billing.models_payment import Payment


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

    elif tab == "payments":
        filter_data = request.session.get("payment_filter", None)

        if filter_data:
            filter = PaymentFilter(filter_data)
            payments = filter.qs
        else:
            payments = Payment.objects.all().select_related("matter").order_by("-date")

    page = request.GET.get("page")

    pagination = Paginator(
        invoices if tab == "invoices" else payments, per_page=10
    ).get_page(page)

    context["pagination"] = pagination
    context["objects"] = pagination.object_list

    return render(request, "billing/billing-main.html", context)


@login_required
def set_tab(request, tab):
    request.session["billing_tab"] = tab
    request.session.modified = True

    return redirect("/billing")
