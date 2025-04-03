from apps.billing.invoices.filters import InvoiceFilter
from apps.billing.invoices.models import INVOICE_STATUS, Invoice
from apps.management.pagination import CustomPaginator


def get_invoice_data(request):
    filter_data = request.session.get("invoices_filter", {})

    if filter_data:
        filter = InvoiceFilter(filter_data)
        invoices = filter.qs
    else:
        invoices = (
            Invoice.objects.all()
            .select_related("matter", "created_by")
            .order_by("-created_at")
        )

    total_fees = sum(invoice.value["net_fees"] for invoice in invoices)
    total_expenses = sum(invoice.value["net_expenses"] for invoice in invoices)
    total = total_fees + total_expenses

    pagination = CustomPaginator(
        invoices, per_page=20, request=request, session_key="invoices_pagination"
    )

    selected_status = filter_data.get("status", "") if filter_data else ""

    context = {
        "pagination": pagination,
        "session_key": "invoices_pagination",
        "trigger_key": "invoicesChanged",
        "objects": pagination.get_object_list(),
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "total": total,
        "status_options": INVOICE_STATUS,
        "selected_status": selected_status,
    }

    return context
