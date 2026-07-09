import os
from datetime import datetime
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.expenses.summary import (
    calculate_summary as calculate_expense_summary,
)
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.flat_fees.summary import (
    calculate_summary as calculate_flat_fee_summary,
)
from apps.activity.time.models import TimeEntry
from apps.activity.time.summary import calculate_summary as calculate_time_summary
from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.functions import generate_ledes_98b
from apps.invoicing.invoices.get_invoice_data import get_invoice_data
from apps.invoicing.payments.forms import PaymentForm
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.models import Matter
from apps.trust.models import Transaction
from utils.toasts import toast_error, toast_success

from .filters import InvoiceFilter
from .forms import EditInvoiceForm, InvoiceForm
from .functions import generate_invoice
from .functions.generate_invoice import store_invoice_pdf
from .functions.send_invoice import (
    InvoiceSendError,
    days_since_sent,
    send_invoice,
    send_reminder,
)
from .models import Invoice


@login_required
def invoices_index(request):
    invoice_data = get_invoice_data(request)

    context = {
        "app": "invoicing",
        "subapp": "invoices",
        "view": "list",
    } | invoice_data

    return render(request, "invoicing/invoices/main.html", context)


@login_required
def invoices_list(request):
    invoice_data = get_invoice_data(request)

    context = {
        "app": "invoicing",
        "subapp": "invoices",
        "view": "list",
    }

    context = context | invoice_data

    return render(request, "invoicing/invoices/list.html", context)


TIME_SORT_FIELDS = {"date", "actions"}
EXPENSE_SORT_FIELDS = {"date", "description"}


def _invoice_time_selection_key(pk):
    """Session key for the per-invoice time-entry bulk selection."""
    return get_session_key("invoice_selected_time", pk)


def _invoice_time_order_key(pk):
    """Session key for the per-invoice time-entry sort order."""
    return get_session_key("invoice_time_order", pk)


def _toggle_order(current, field):
    """Return the next sort value when a column header is clicked."""
    if current.lstrip("-") == field:
        return field if current.startswith("-") else f"-{field}"
    return field


def _get_invoice_time_context(request, invoice):
    """Build context for the invoice time entries tab."""
    session_key = f"invoice_{invoice.pk}_time_pagination"
    order = request.session.get(_invoice_time_order_key(invoice.pk), "date")
    entries = TimeEntry.objects.filter(invoice=invoice).order_by(order, "id")
    summary = calculate_time_summary(entries)
    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key=session_key
    )
    objects = pagination.get_object_list()

    selected_time = get_selected_ids(request, _invoice_time_selection_key(invoice.pk))
    visible_ids = [entry.id for entry in objects]
    can_bulk_select = invoice.status == "DRAFT" and (
        request.user.is_admin or request.user.perm_financial
    )

    return {
        "objects": objects,
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": "timeChanged",
        "summary": summary,
        "selected_time": selected_time,
        "all_selected": all_visible_selected(selected_time, visible_ids),
        "can_bulk_select": can_bulk_select,
        "current_order": order.lstrip("-"),
    }


@login_required
def invoices_detail_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "time",
        "invoice": invoice,
        "view": "detail",
    }
    context.update(_get_invoice_time_context(request, invoice))

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def invoices_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "time",
        "invoice": invoice,
        "view": "detail",
    }
    context.update(_get_invoice_time_context(request, invoice))

    return render(request, "invoicing/invoices/detail/detail.html", context)


@login_required
def invoice_tab_content(request, pk, tab):
    """Return tab content for HTMX tab switching (matches matter detail pattern)."""
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": tab,
        "invoice": invoice,
        "view": "detail",
    }

    if tab == "time":
        context.update(_get_invoice_time_context(request, invoice))
    elif tab == "expenses":
        context.update(_get_invoice_expense_context(request, invoice))
    elif tab == "flat-fees":
        flat_fees_key = f"invoice_{pk}_flat_fees_pagination"
        flat_fees = FlatFeeEntry.objects.filter(invoice=invoice).order_by("date", "id")
        summary = calculate_flat_fee_summary(flat_fees)
        pagination = CustomPaginator(
            flat_fees,
            per_page=10,
            request=request,
            session_key=flat_fees_key,
        )
        context.update(
            {
                "objects": pagination.get_object_list(),
                "pagination": pagination,
                "session_key": flat_fees_key,
                "trigger_key": "flatFeesChanged",
                "summary": summary,
            }
        )
    elif tab == "preview":
        context["file_url"] = reverse_lazy(
            "invoicing:invoices-pdf", kwargs={"pk": invoice.pk}
        )

    return render(request, "invoicing/invoices/detail/detail-tab-content.html", context)


@login_required
def invoice_details_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "details",
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def invoice_history_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "history",
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def pdf_preview_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "preview",
        "file_url": reverse_lazy("invoicing:invoices-pdf", kwargs={"pk": invoice.pk}),
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def pdf_preview(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "preview",
        "file_url": reverse_lazy("invoicing:invoices-pdf", kwargs={"pk": invoice.pk}),
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/preview/preview.html", context)


@login_required
def invoice_time_entries_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "time",
        "invoice": invoice,
        "view": "detail",
    }
    context.update(_get_invoice_time_context(request, invoice))

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def invoice_time_entries(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "time",
        "invoice": invoice,
        "view": "detail",
    }
    context.update(_get_invoice_time_context(request, invoice))

    return render(request, "invoicing/invoices/time/list.html", context)


@login_required
@require_POST
def invoice_time_toggle_select(request, pk, entry_id):
    """Toggle selection of a single time entry on this invoice."""
    get_object_or_404(TimeEntry, pk=entry_id, invoice_id=pk)
    toggle_id(request, _invoice_time_selection_key(pk), entry_id)

    return selection_response("timeChanged")


@login_required
@require_POST
def invoice_time_select_all(request, pk):
    """Select or deselect all visible time entries on this invoice."""
    invoice = get_object_or_404(Invoice, pk=pk)
    context = _get_invoice_time_context(request, invoice)
    visible_ids = [entry.id for entry in context["objects"]]

    select_all_ids(request, _invoice_time_selection_key(pk), visible_ids)

    return selection_response("timeChanged")


@login_required
@require_POST
def invoice_time_clear_selection(request, pk):
    """Clear the time-entry selection for this invoice."""
    clear_selected_ids(request, _invoice_time_selection_key(pk))

    return selection_response("timeChanged")


@login_required
@require_POST
def invoice_time_bulk_update_comp(request, pk):
    """Bulk-apply comp (non-billable) status to selected invoice time entries."""
    if not request.user.is_admin and not request.user.perm_financial:
        return HttpResponseForbidden()

    invoice = get_object_or_404(Invoice, pk=pk)
    key = _invoice_time_selection_key(pk)
    selected_time = get_selected_ids(request, key)

    if not selected_time:
        return HttpResponse(status=400, content="No time entries selected.")

    comp_value = request.POST.get("comp")
    if comp_value in ["true", "false"]:
        comp_bool = comp_value == "true"
        entries = TimeEntry.objects.filter(id__in=selected_time, invoice=invoice)

        for entry in entries:
            entry.comp = comp_bool
            entry.save()

        clear_selected_ids(request, key)

    return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})


@login_required
@require_POST
def invoice_time_order_by(request, pk, order):
    """Toggle the sort order of an invoice's time entries by column."""
    if order not in TIME_SORT_FIELDS:
        return HttpResponse(status=400)

    key = _invoice_time_order_key(pk)
    current = request.session.get(key, "")
    request.session[key] = _toggle_order(current, order)

    return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})


def _invoice_expense_order_key(pk):
    """Session key for the per-invoice expense sort order."""
    return get_session_key("invoice_expense_order", pk)


def _get_invoice_expense_context(request, invoice):
    """Build context for the invoice expense entries tab."""
    session_key = f"invoice_{invoice.pk}_expenses_pagination"
    order = request.session.get(_invoice_expense_order_key(invoice.pk), "date")
    expenses = ExpenseEntry.objects.filter(invoice=invoice).order_by(order, "id")
    summary = calculate_expense_summary(expenses)

    pagination = CustomPaginator(
        expenses,
        per_page=10,
        request=request,
        session_key=session_key,
    )

    return {
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": "expensesChanged",
        "summary": summary,
        "current_order": order.lstrip("-"),
    }


@login_required
@require_POST
def invoice_expense_order_by(request, pk, order):
    """Toggle the sort order of an invoice's expense entries by column."""
    if order not in EXPENSE_SORT_FIELDS:
        return HttpResponse(status=400)

    key = _invoice_expense_order_key(pk)
    current = request.session.get(key, "")
    request.session[key] = _toggle_order(current, order)

    return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})


@login_required
def invoice_expense_entries_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "expenses",
        "invoice": invoice,
        "view": "detail",
    }
    context.update(_get_invoice_expense_context(request, invoice))

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def invoice_expense_entries(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "expenses",
        "invoice": invoice,
        "view": "detail",
    }
    context.update(_get_invoice_expense_context(request, invoice))

    return render(request, "invoicing/invoices/expenses/list.html", context)


@login_required
def invoice_flat_fee_entries_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    session_key = f"invoice_{pk}_flat_fees_pagination"

    flat_fees = FlatFeeEntry.objects.filter(invoice=invoice).order_by("date", "id")
    summary = calculate_flat_fee_summary(flat_fees)

    pagination = CustomPaginator(
        flat_fees,
        per_page=10,
        request=request,
        session_key=session_key,
    )

    context = {
        "app": "invoicing",
        "subapp": "flat-fees",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": "flatFeesChanged",
        "invoice": invoice,
        "summary": summary,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def invoice_flat_fee_entries(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    session_key = f"invoice_{pk}_flat_fees_pagination"

    flat_fees = FlatFeeEntry.objects.filter(invoice=invoice).order_by("date", "id")
    summary = calculate_flat_fee_summary(flat_fees)

    pagination = CustomPaginator(
        flat_fees,
        per_page=10,
        request=request,
        session_key=session_key,
    )

    context = {
        "app": "invoicing",
        "subapp": "flat-fees",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": "flatFeesChanged",
        "invoice": invoice,
        "summary": summary,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/flat-fees/list.html", context)


@login_required
def quick_invoice_payment(request, pk, payment_type):
    current_date = datetime.now().date()

    try:
        invoice = Invoice.objects.get(pk=pk)
    except (Invoice.DoesNotExist, Exception):
        return HttpResponse(status=404)
    invoice_value = invoice.value["final_total"]

    form = PaymentForm(
        request.POST or None,
        use_required_attribute=False,
        initial={
            "amount": invoice_value,
            "matter": invoice.matter,
            "detail": f"Invoice {invoice.id}",
        },
    )

    if payment_type == "trust":
        form.fields["payment_method"].initial = "TRUST"

    if request.method == "POST" and form.is_valid():
        payment = form.save()

        # Auto-allocate payment to invoice
        amount_to_allocate = min(payment.amount, invoice.amount_remaining)
        if amount_to_allocate > 0:
            PaymentApplication.objects.create(
                payment=payment,
                invoice=invoice,
                amount_applied=amount_to_allocate,
            )

        if payment_type == "trust":
            Transaction.objects.create(
                contact=invoice.matter.client,
                date=current_date,
                type="Withdrawal",
                amount=payment.amount,
                description=f"Invoice {invoice.id}",
            )

        return HttpResponse(status=302, headers={"HX-Redirect": "/invoicing/payments"})

    return render(
        request,
        "invoicing/invoices/quick-pay-form.html",
        {"form": form, "invoice": invoice, "payment_type": payment_type},
    )


@login_required
def invoices_add(request):
    if request.method == "POST":
        form = InvoiceForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.created_by = request.user
            invoice.save()
            store_invoice_pdf(invoice, request)

            filter_data = request.session.get("invoices_filter", {})
            filter_data["status"] = "DRAFT"
            request.session["invoices_filter"] = filter_data
            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "invoicesChanged, unbilledListChanged"},
            )

    else:
        form = InvoiceForm(use_required_attribute=False)

        # Check if a matter was specified via GET parameter
        matter_id = request.GET.get("matter")

        entries = TimeEntry.objects.filter(
            invoice__isnull=True, entered=False, date__gte="2024-01-01"
        ).values_list("matter", flat=True)

        expenses = ExpenseEntry.objects.filter(
            invoice__isnull=True, entered=False
        ).values_list("matter", flat=True)

        # Combine all matter IDs (including the specified one if provided)
        matter_ids = list(chain(entries, expenses))
        if matter_id:
            matter_ids.append(int(matter_id))
            form.fields["matter"].initial = matter_id

        matter_list = (
            Matter.objects.filter(id__in=matter_ids).distinct().order_by("name")
        )

        # Create a list of matters with unbilled time for the dropdown
        matters_with_unbilled = []
        for matter in matter_list:
            unbilled_amount = matter.value["unbilled"]["net_fees_and_expenses"]
            matters_with_unbilled.append(
                (matter.id, f"{matter.name}\u00a0\u00a0\u00a0(${unbilled_amount:,.2f})")
            )

        form.fields["matter"].queryset = matter_list
        form.fields["matter"].widget.choices = matters_with_unbilled

    return render(request, "invoicing/invoices/form.html", {"form": form})


@login_required
def invoices_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status == "VOID":
        return HttpResponse(status=403)

    if request.method == "POST":
        form = EditInvoiceForm(
            request.POST, instance=invoice, use_required_attribute=False
        )
        if form.is_valid():
            invoice.save()
            store_invoice_pdf(invoice, request)

            return HttpResponse(
                status=204, headers={"HX-Trigger": "invoiceDetailChanged"}
            )

    else:
        form = EditInvoiceForm(instance=invoice, use_required_attribute=False)

    context = {"form": form, "invoice": invoice}

    return render(request, "invoicing/invoices/edit.html", context)


@login_required
def invoices_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status in ["DRAFT", "APPROVED"]:
        invoice.delete()
        return redirect("invoicing:invoices-index")

    if invoice.status == "VOID" and request.user.is_admin:
        invoice.delete()
        return redirect("invoicing:invoices-index")

    return HttpResponse(status=403)


@login_required
def invoices_void_confirm(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    return render(request, "invoicing/invoices/confirm-void.html", {"invoice": invoice})


@login_required
def invoices_void(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status in ["DRAFT", "APPROVED"]:
        return HttpResponse(status=400)

    if not invoice.pdf_file:
        store_invoice_pdf(invoice, request)

    invoice.void()

    return HttpResponse(
        status=204,
        headers={"HX-Trigger": "invoicesChanged, invoiceDetailChanged"},
    )


@login_required
def invoices_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    notation = "DRAFT - " if invoice.status == "DRAFT" else ""
    notation = "VOID - " if invoice.status == "VOID" else notation
    filename = f'filename="{notation}Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'

    if invoice.pdf_file and invoice.status != "DRAFT":
        response = HttpResponse(invoice.pdf_file.read(), content_type="application/pdf")
        response["Content-Disposition"] = filename
        return response

    file = generate_invoice(invoice, request)

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        response["Content-Disposition"] = filename

    os.unlink(file.name)

    return response


@login_required
def invoices_pdf_download(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    notation = "DRAFT - " if invoice.status == "DRAFT" else ""
    notation = "VOID - " if invoice.status == "VOID" else notation
    filename = f'filename="{notation}Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'

    if invoice.pdf_file and invoice.status != "DRAFT":
        response = HttpResponse(invoice.pdf_file.read(), content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; {filename}"
        return response

    file = generate_invoice(invoice, request)

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response


@login_required
def invoice_ledes_98b(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status == "VOID":
        return HttpResponse(status=400)

    ledes_file = generate_ledes_98b(invoice)

    with open(ledes_file.name, "rb") as file:
        response = HttpResponse(file.read(), content_type="text/plain")

        filename = f'attachment; filename="LEDES98B - {invoice.id} - {invoice.matter} - {invoice.date_issued}.txt"'
        response["Content-Disposition"] = filename

    os.unlink(ledes_file.name)

    return response


@login_required
def invoices_filter(request):
    if request.method == "POST":
        # Merge into existing session so the status quick-filter (and any
        # other non-form state) is preserved; skip the CSRF token explicitly.
        filter_data = dict(request.session.get("invoices_filter", {}))
        for key, val in request.POST.items():
            if key == "csrfmiddlewaretoken":
                continue
            filter_data[key] = val
        request.session["invoices_filter"] = filter_data

        return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})
    else:
        filter_data = request.session.get("invoices_filter", {})

        if filter_data:
            filter = InvoiceFilter(
                filter_data,
                queryset=Invoice.objects.all()
                .select_related("matter", "created_by")
                .order_by("-created_at"),
            )
        else:
            default_filter = {"order_by": "-date_issued"}

            filter = InvoiceFilter(
                default_filter,
                queryset=Invoice.objects.all()
                .select_related("matter", "created_by")
                .order_by("-created_at"),
            )
        return render(request, "invoicing/invoices/filter.html", {"filter": filter})


@login_required
def invoices_filter_status(request, status):
    filter_data = request.session.get("invoices_filter", {})
    filter_data["status"] = status

    request.session["invoices_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})


@login_required
def order_by_invoices(request, order):
    filter_data = request.session.get("invoices_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["invoices_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})


@login_required
def invoices_edit_status(request, pk, status, view):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status == "VOID":
        return HttpResponse(status=400)

    # A sent invoice — one actually emailed and logged in its transmission
    # history (date_sent set) — is locked forward: it can't drop back to
    # APPROVED or DRAFT. A manually-set SENT that was never emailed still can.
    if status in ("APPROVED", "DRAFT") and invoice.date_sent:
        response = HttpResponse(status=204)  # 204 = no swap; dropdown unchanged
        toast_error(
            response,
            f"Invoice #{invoice.id} has already been sent, so it can't be moved "
            f"back to {status.title()}.",
        )
        return response

    invoice.status = status
    invoice.save()

    if status in ["APPROVED", "SENT"]:
        store_invoice_pdf(invoice, request)

    trigger = "invoicesChanged" if view == "list" else "invoiceDetailChanged"

    return HttpResponse(status=204, headers={"HX-Trigger": trigger})


@login_required
def invoices_send(request, pk):
    """Email the invoice PDF to the client and record the transmission. GET
    renders the confirmation modal; POST sends and returns 204 (closes the modal,
    refreshes the detail) or re-renders the modal with an error."""
    invoice = get_object_or_404(Invoice, pk=pk)
    client = invoice.matter.client if invoice.matter else None

    if request.method == "POST":
        to = (request.POST.get("to") or "").strip()
        cc = (request.POST.get("cc") or "").strip()
        message = request.POST.get("message", "")
        recipient = to or (client.email if client else "")
        try:
            send_invoice(
                invoice,
                to=to or None,
                cc=cc or None,
                message=message,
                sent_by=request.user,
                request=request,
            )
        except InvoiceSendError as exc:
            context = {
                "invoice": invoice,
                "default_to": to,
                "default_cc": cc,
                "default_message": message,
                "error": str(exc),
            }
            return render(request, "invoicing/invoices/send.html", context)

        # Refresh both surfaces: the detail page and the list (where the Send
        # button lives on APPROVED rows and the row should flip to SENT).
        response = HttpResponse(
            status=204,
            headers={"HX-Trigger": "invoiceDetailChanged, invoicesChanged"},
        )
        toast_success(response, f"Invoice #{invoice.id} sent to {recipient}.")
        return response

    context = {
        "invoice": invoice,
        "default_to": client.email if client else "",
        "default_cc": "",
        "default_message": invoice.message or "",
        "error": "",
    }
    return render(request, "invoicing/invoices/send.html", context)


@login_required
def invoices_send_reminder(request, pk):
    """Email a payment reminder for an already-sent invoice. GET renders the
    modal (shared with send/resend); POST sends and returns 204 (closes the
    modal, refreshes the list/detail) or re-renders the modal with an error."""
    invoice = get_object_or_404(Invoice, pk=pk)
    client = invoice.matter.client if invoice.matter else None

    if request.method == "POST":
        to = (request.POST.get("to") or "").strip()
        cc = (request.POST.get("cc") or "").strip()
        message = request.POST.get("message", "")
        recipient = to or (client.email if client else "")
        try:
            send_reminder(
                invoice,
                to=to or None,
                cc=cc or None,
                message=message,
                sent_by=request.user,
                request=request,
            )
        except InvoiceSendError as exc:
            context = {
                "invoice": invoice,
                "reminder": True,
                "days_since": days_since_sent(invoice),
                "default_to": to,
                "default_cc": cc,
                "default_message": message,
                "error": str(exc),
            }
            return render(request, "invoicing/invoices/send.html", context)

        response = HttpResponse(
            status=204,
            headers={"HX-Trigger": "invoiceDetailChanged, invoicesChanged"},
        )
        toast_success(
            response, f"Reminder for invoice #{invoice.id} sent to {recipient}."
        )
        return response

    context = {
        "invoice": invoice,
        "reminder": True,
        "days_since": days_since_sent(invoice),
        "default_to": client.email if client else "",
        "default_cc": "",
        "default_message": "",
        "error": "",
    }
    return render(request, "invoicing/invoices/send.html", context)
