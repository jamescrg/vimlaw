from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.contacts.models import Contact
from apps.invoicing.pay.balance import matter_balance_cents
from apps.invoicing.requests.filters import PaymentRequestFilter
from apps.invoicing.requests.models import PaymentRequest, PaymentRequestTransmission
from apps.invoicing.requests.send import (
    PaymentRequestSendError,
    days_since_requested,
    send_payment_request,
    send_request_reminder,
)
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from utils.toasts import toast_success

# Filter keys that don't count toward the "filter is active" toolbar highlight:
# status has its own quick-buttons, and the POST carries the CSRF token.
_NON_FILTER_KEYS = ("status", "order_by", "csrfmiddlewaretoken")


def _requests_context(request):
    filter_data = request.session.get("requests_filter", {})
    base = (
        PaymentRequest.objects.select_related(
            "matter", "client", "payment", "trust_transaction"
        )
        .annotate(
            # Successful transmissions (sends and reminders) — the ×N badge.
            annotated_send_count=Coalesce(
                Subquery(
                    PaymentRequestTransmission.objects.filter(
                        payment_request=OuterRef("pk"), status="sent"
                    )
                    .values("payment_request")
                    .annotate(n=Count("pk"))
                    .values("n")
                ),
                0,
            ),
            annotated_last_sent_at=Subquery(
                PaymentRequestTransmission.objects.filter(
                    payment_request=OuterRef("pk"), status="sent"
                )
                .order_by("-sent_at")
                .values("sent_at")[:1]
            ),
        )
        .order_by("-created_at")
    )
    requests = (
        PaymentRequestFilter(filter_data, queryset=base).qs if filter_data else base
    )
    pagination = CustomPaginator(
        requests, per_page=10, request=request, session_key="requests_pagination"
    )
    filter_active = bool(
        filter_data
        and any(
            v
            for k, v in filter_data.items()
            if k not in _NON_FILTER_KEYS and v not in (None, "")
        )
    )
    return {
        "app": "invoicing",
        "subapp": "requests",
        "pagination": pagination,
        "session_key": "requests_pagination",
        "trigger_key": "requestsChanged",
        "objects": pagination.get_object_list(),
        "current_status": filter_data.get("status", ""),
        "filter_active": filter_active,
    }


@login_required
def requests_index(request):
    return render(request, "invoicing/requests/main.html", _requests_context(request))


@login_required
def requests_list(request):
    return render(request, "invoicing/requests/list.html", _requests_context(request))


@login_required
def requests_filter(request):
    """Filter modal: matter / date / status. POST stores the cleaned filter in
    the session; GET renders the modal bound to the current filter."""
    if request.method == "POST":
        request.session["requests_filter"] = {
            k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"
        }
        return HttpResponse(status=204, headers={"HX-Trigger": "requestsChanged"})
    filter_data = request.session.get("requests_filter")
    base = PaymentRequest.objects.select_related("matter").order_by("-created_at")
    payment_request_filter = PaymentRequestFilter(filter_data or None, queryset=base)
    return render(
        request, "invoicing/requests/filter.html", {"filter": payment_request_filter}
    )


@login_required
def requests_filter_status(request, status):
    """Quick status filter (Sent / Paid / Canceled). Toggling the active one or
    passing 'all' clears it. Shares the session filter dict with the modal."""
    filter_data = dict(request.session.get("requests_filter", {}))
    if status == "all" or filter_data.get("status") == status:
        filter_data.pop("status", None)
    else:
        filter_data["status"] = status
    request.session["requests_filter"] = filter_data
    request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": "requestsChanged"})


def _open_matters():
    return Matter.objects.exclude(status__in=["Pending", "Closed"]).order_by("name")


@login_required
def requests_new(request):
    """Create + send a payment request for a firm-set amount (defaulting to the
    matter's full open balance, adjustable down for a partial payment)."""
    if request.method == "POST":
        matter_id = request.POST.get("matter") or ""
        to = (request.POST.get("to") or "").strip()
        cc = (request.POST.get("cc") or "").strip()
        message = request.POST.get("message", "")
        amount_raw = (request.POST.get("amount") or "").strip()
        attach_statement = "attach_statement" in request.POST
        attach_invoices = "attach_invoices" in request.POST
        matter = _open_matters().filter(pk=matter_id).first() if matter_id else None

        error = ""
        amount = None
        if not matter:
            error = "Please select a matter."
        else:
            balance = Decimal(matter_balance_cents(matter)) / 100
            if balance <= 0:
                error = "This matter has no open balance to request."
            elif amount_raw:
                try:
                    amount = Decimal(amount_raw.replace("$", "").replace(",", ""))
                except InvalidOperation:
                    error = "Enter a valid dollar amount."
            else:
                amount = balance  # blank → request the full balance
            if not error and amount is not None:
                if amount <= 0:
                    error = "Amount must be greater than zero."
                elif amount > balance:
                    error = f"Amount can't exceed the balance due (${balance:.2f})."

        if not error:
            payment_request = PaymentRequest(
                matter=matter,
                amount_requested=amount,
                recipient_email=to,
                status="SENT",
            )
            # Persist + send together: if the email fails (incl. validation),
            # roll back so we never leave an unsent request behind.
            try:
                with transaction.atomic():
                    payment_request.save()
                    send_payment_request(
                        payment_request,
                        to=to,
                        cc=cc,
                        message=message,
                        attach_statement=attach_statement,
                        attach_invoices=attach_invoices,
                        sent_by=request.user,
                        request=request,
                    )
            except PaymentRequestSendError as exc:
                error = str(exc)
            else:
                response = HttpResponse(
                    status=204, headers={"HX-Trigger": "requestsChanged"}
                )
                toast_success(response, f"Payment request sent to {to}.")
                return response

        context = {
            "matters": _open_matters(),
            "matter_id": matter_id,
            "to": to,
            "cc": cc,
            "message": message,
            "amount": amount_raw,
            "attach_statement": attach_statement,
            "attach_invoices": attach_invoices,
            "error": error,
        }
        return render(request, "invoicing/requests/form.html", context)

    context = {
        "matters": _open_matters(),
        "matter_id": "",
        "to": "",
        "cc": "",
        "message": "",
        "amount": "",
        "attach_statement": True,
        "attach_invoices": True,
        "error": "",
    }
    return render(request, "invoicing/requests/form.html", context)


@login_required
def requests_matter_fields(request):
    """On matter change, return the To input (client email) + the Amount input
    (the matter's balance due, which the firm can then adjust down). htmx swaps
    the To field and the Amount field (out-of-band) into the request modal."""
    matter_id = request.GET.get("matter")
    email = ""
    amount = ""
    if matter_id:
        matter = Matter.objects.filter(pk=matter_id).select_related("client").first()
        if matter:
            if matter.client:
                email = matter.client.email or ""
            balance_cents = matter_balance_cents(matter)
            if balance_cents > 0:
                amount = f"{Decimal(balance_cents) / 100:.2f}"
    return render(
        request,
        "invoicing/requests/matter_fields.html",
        {"to": email, "amount": amount},
    )


def _trust_clients():
    return Contact.objects.active_or_pending_clients().order_by("name")


@login_required
def requests_new_trust(request):
    """Create + send a trust deposit request for a client (firm-set amount,
    deposited to the trust account).

    When opened from the trust tab (``?next=requests``) a successful send
    redirects the user to the Requests tab, so it's clear they created a *request*
    (not a posted trust transaction); from the Requests tab it stays put and
    refreshes the list.
    """
    next_tab = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST":
        client_id = request.POST.get("client") or ""
        to = (request.POST.get("to") or "").strip()
        cc = (request.POST.get("cc") or "").strip()
        message = request.POST.get("message", "")
        amount_raw = (request.POST.get("amount") or "").strip()
        client = _trust_clients().filter(pk=client_id).first() if client_id else None

        error = ""
        amount = None
        if not client:
            error = "Please select a client."
        elif not amount_raw:
            error = "Enter a deposit amount."
        else:
            try:
                amount = Decimal(amount_raw.replace("$", "").replace(",", ""))
            except InvalidOperation:
                error = "Enter a valid dollar amount."
            else:
                if amount <= 0:
                    error = "Amount must be greater than zero."

        if not error:
            payment_request = PaymentRequest(
                account="trust",
                client=client,
                amount_requested=amount,
                recipient_email=to,
                status="SENT",
            )
            try:
                with transaction.atomic():
                    payment_request.save()
                    send_payment_request(
                        payment_request,
                        to=to,
                        cc=cc,
                        message=message,
                        sent_by=request.user,
                        request=request,
                    )
            except PaymentRequestSendError as exc:
                error = str(exc)
            else:
                # From the trust tab: send the user to the Requests tab (the new
                # request lands there). From the Requests tab: stay + refresh.
                if next_tab == "requests":
                    # Force the Sent filter first — a new request is SENT, and the
                    # user's filter may have been on Paid/Canceled where it
                    # wouldn't show. Preserve any other filter keys.
                    filter_data = dict(request.session.get("requests_filter", {}))
                    filter_data["status"] = "SENT"
                    request.session["requests_filter"] = filter_data
                    request.session.modified = True
                    return HttpResponse(
                        status=204,
                        headers={"HX-Redirect": reverse("invoicing:requests-index")},
                    )
                response = HttpResponse(
                    status=204, headers={"HX-Trigger": "requestsChanged"}
                )
                toast_success(response, f"Trust deposit request sent to {to}.")
                return response

        context = {
            "clients": _trust_clients(),
            "client_id": client_id,
            "to": to,
            "cc": cc,
            "message": message,
            "amount": amount_raw,
            "error": error,
            "next": next_tab,
        }
        return render(request, "invoicing/requests/trust_form.html", context)

    context = {
        "clients": _trust_clients(),
        "client_id": "",
        "to": "",
        "cc": "",
        "message": "",
        "amount": "",
        "error": "",
        "next": next_tab,
    }
    return render(request, "invoicing/requests/trust_form.html", context)


@login_required
def requests_client_email(request):
    """On client change, return the To input pre-filled with the client's email."""
    client_id = request.GET.get("client")
    email = ""
    if client_id:
        client = Contact.objects.filter(pk=client_id).first()
        if client:
            email = client.email or ""
    return render(request, "invoicing/requests/to_input.html", {"to": email})


@login_required
def requests_cancel(request, pk):
    payment_request = get_object_or_404(PaymentRequest, pk=pk)
    if payment_request.status == "SENT":
        payment_request.status = "CANCELED"
        payment_request.save(update_fields=["status"])
    return render(
        request, "invoicing/requests/row.html", {"payment_request": payment_request}
    )


@login_required
def requests_resend(request, pk):
    """Resend an existing request's email (same link/amount). GET renders the
    modal pre-filled with the stored recipient; POST re-sends."""
    payment_request = get_object_or_404(PaymentRequest, pk=pk)
    if request.method == "POST":
        to = (request.POST.get("to") or "").strip()
        cc = (request.POST.get("cc") or "").strip()
        message = request.POST.get("message", "")
        attach_statement = "attach_statement" in request.POST
        attach_invoices = "attach_invoices" in request.POST
        error = ""
        try:
            send_payment_request(
                payment_request,
                to=to,
                cc=cc,
                message=message,
                attach_statement=attach_statement,
                attach_invoices=attach_invoices,
                sent_by=request.user,
                request=request,
            )
        except PaymentRequestSendError as exc:
            error = str(exc)
        if not error:
            response = HttpResponse(
                status=204, headers={"HX-Trigger": "requestsChanged"}
            )
            label = (
                "Trust deposit request"
                if payment_request.is_trust
                else "Payment request"
            )
            toast_success(response, f"{label} resent to {to}.")
            return response
        context = {
            "payment_request": payment_request,
            "to": to,
            "cc": cc,
            "message": message,
            "attach_statement": attach_statement,
            "attach_invoices": attach_invoices,
            "error": error,
        }
        return render(request, "invoicing/requests/resend.html", context)

    context = {
        "payment_request": payment_request,
        "to": payment_request.recipient_email,
        "cc": "",
        "message": "",
        "attach_statement": True,
        "attach_invoices": True,
        "error": "",
    }
    return render(request, "invoicing/requests/resend.html", context)


@login_required
def requests_send_reminder(request, pk):
    """Email a reminder for an already-sent request. GET renders the modal
    (shared with resend); POST sends and returns 204 or re-renders with an
    error."""
    payment_request = get_object_or_404(PaymentRequest, pk=pk)
    if request.method == "POST":
        to = (request.POST.get("to") or "").strip()
        cc = (request.POST.get("cc") or "").strip()
        message = request.POST.get("message", "")
        error = ""
        try:
            send_request_reminder(
                payment_request,
                to=to,
                cc=cc,
                message=message,
                sent_by=request.user,
                request=request,
            )
        except PaymentRequestSendError as exc:
            error = str(exc)
        if not error:
            response = HttpResponse(
                status=204, headers={"HX-Trigger": "requestsChanged"}
            )
            label = (
                "Trust deposit reminder"
                if payment_request.is_trust
                else "Payment reminder"
            )
            toast_success(response, f"{label} sent to {to}.")
            return response
        context = {
            "payment_request": payment_request,
            "reminder": True,
            "days_since": days_since_requested(payment_request),
            "to": to,
            "cc": cc,
            "message": message,
            "error": error,
        }
        return render(request, "invoicing/requests/resend.html", context)

    context = {
        "payment_request": payment_request,
        "reminder": True,
        "days_since": days_since_requested(payment_request),
        "to": payment_request.recipient_email,
        "cc": "",
        "message": "",
        "error": "",
    }
    return render(request, "invoicing/requests/resend.html", context)
