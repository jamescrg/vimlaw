"""Public, no-login invoice payment page.

The client opens a tokenized link (`/pay/<signed-token>/`), sees the invoice
summary, enters card or bank details into the active processor's hosted fields
(which tokenize client-side — card/bank data never reaches us), and submits the
one-time token to `pay_charge`, which charges it via the configured processor.

This is the app's only record-exposing public surface, so access is gated by the
signed, expiring token (see `utils.signing`), not a session.

On a successful charge the payment is recorded and applied to the invoice (see
`recording`); the settlement/return webhook (`processor_webhook` →
`reconcile`) later confirms or reverses it.
"""

import json
from dataclasses import replace
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.invoicing.invoices.models import Invoice
from apps.invoicing.pay.balance import (
    matter_open_invoices,
    record_matter_balance_payment,
    record_trust_deposit,
    request_charge_cents,
)
from apps.invoicing.pay.recording import record_payment
from apps.invoicing.processors import ChargeError, get_processor
from apps.invoicing.processors.base import ClientConfig
from apps.invoicing.requests.models import PaymentRequest
from utils.signing import read_payment_token, read_request_token


def _to_cents(amount):
    return int((Decimal(str(amount)) * 100).to_integral_value())


# Firm-configurable payment-page look (Settings → Payments, on Company). Kept in
# data, not hardcoded, so each firm running this open-source app picks its own.
# Full per-theme palette (page gradient + card/border/button), light + dark. The
# "blue" theme is the firm's original slate look (they refer to slate as "blue");
# "gray" is a neutral gray. The whole card — not just the background — swaps, so
# each theme reads as one coherent palette.
_PAY_PALETTES = {
    "blue": {  # slate
        "gradient": "#f1f5f9 linear-gradient(180deg, #cbd5e1 0%, #f1f5f9 70%, #f1f5f9 100%) fixed",
        "gradient_dark": "#0f172a linear-gradient(180deg, #1e293b 0%, #0f172a 70%, #0f172a 100%) fixed",
        "card": "#f8fafc",
        "card_dark": "#1e293b",
        "border": "#cbd5e1",
        "border_dark": "#334155",
        "btn": "#cbd5e1",
        "btn_dark": "#475569",
    },
    "gray": {  # neutral
        "gradient": "#f5f5f5 linear-gradient(180deg, #d4d4d4 0%, #f5f5f5 70%, #f5f5f5 100%) fixed",
        "gradient_dark": "#0a0a0a linear-gradient(180deg, #262626 0%, #0a0a0a 70%, #0a0a0a 100%) fixed",
        "card": "#fafafa",
        "card_dark": "#171717",
        "border": "#e5e5e5",
        "border_dark": "#262626",
        "btn": "#e5e5e5",
        "btn_dark": "#404040",
    },
}


def _pay_style(company):
    """Resolve the payment-page style strings from the firm's Company settings."""
    font = getattr(company, "payment_font", "serif") or "serif"
    background = getattr(company, "payment_background", "gray") or "gray"
    sans = font == "sans"
    palette = _PAY_PALETTES.get(background, _PAY_PALETTES["gray"])
    family = "Noto Sans" if sans else "Noto Serif"
    generic = "sans-serif" if sans else "serif"
    return {
        "pay_font": font,
        "pay_background": background,
        # CSS font-family value for the page (var --pay-font).
        "pay_font_family": f'"{family}", {generic}',
        # Google Fonts stylesheet for the page + Stripe Element iframe.
        "pay_font_link": (
            f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}"
            ":ital,wght@0,100..900;1,100..900&display=swap"
        ),
        "pay_stripe_font_url": (
            f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}"
            ":wght@400;500&display=swap"
        ),
        # Web-safe fallback for cross-origin hosted-field iframes (they can't load
        # the page webfont).
        "pay_iframe_font": (
            "Arial, 'Helvetica Neue', sans-serif"
            if sans
            else "Georgia, 'Times New Roman', serif"
        ),
        "pay_gradient": palette["gradient"],
        "pay_gradient_dark": palette["gradient_dark"],
        "pay_card": palette["card"],
        "pay_card_dark": palette["card_dark"],
        "pay_border": palette["border"],
        "pay_border_dark": palette["border_dark"],
        "pay_btn": palette["btn"],
        "pay_btn_dark": palette["btn_dark"],
    }


def _client_email(matter):
    """Best-effort payer email for a matter's client (for processor receipts)."""
    client = getattr(matter, "client", None)
    return (getattr(client, "email", "") or "").strip()


def _client_info(client):
    """Descriptor a processor can use to sync/attach the paying client to its
    records (Confido). Keyed on our contact id via external_id."""
    if client is None:
        return None
    return {
        "external_id": str(client.id),
        "name": (getattr(client, "name", "") or "").strip(),
        "email": (getattr(client, "email", "") or "").strip(),
        "phone": (getattr(client, "phone1", "") or "").strip(),
    }


def _matter_info(matter):
    """Descriptor for the matter, keyed on our matter id via external_id."""
    if matter is None:
        return None
    return {
        "external_id": str(matter.id),
        "name": (getattr(matter, "name", "") or "").strip(),
    }


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _rate_limited(request, scope, *, limit, window):
    """Best-effort fixed-window limiter keyed by client IP (Django cache)."""
    key = f"ratelimit:{scope}:{_client_ip(request)}"
    try:
        cache.get_or_set(key, 0, window)
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        count = 1
    return count > limit


def _resolve_invoice(token):
    """Return the invoice for a signed token, or raise Http404 with a reason
    suitable for the 'link unavailable' page."""
    try:
        invoice_uuid = read_payment_token(
            token, max_age=settings.INVOICE_PAY_LINK_MAX_AGE
        )
    except signing.SignatureExpired:
        raise Http404("expired")
    except signing.BadSignature:
        raise Http404("invalid")
    return get_object_or_404(Invoice, uuid=invoice_uuid)


def _unavailable(request, reason, *, status):
    return render(
        request, "invoicing/pay/unavailable.html", {"reason": reason}, status=status
    )


def pay_page(request, token):
    try:
        invoice = _resolve_invoice(token)
    except Http404 as exc:
        reason = str(exc)
        if reason == "expired":
            return _unavailable(
                request,
                "This payment link has expired. Please contact us for a new one.",
                status=410,
            )
        return _unavailable(request, "This payment link is invalid.", status=404)

    processor = get_processor()
    config = processor.client_config(invoice)
    matter = invoice.matter
    from apps.settings.models import Company

    company = Company.objects.first()
    context = {
        "invoice": invoice,
        "matter_number": matter.id if matter else "",
        "firm_name": company.name if company else "",
        "amount_due": invoice.amount_remaining,
        "config": config,
        "is_paid": invoice.amount_remaining <= 0,
        # Dev/fake processor: render a simulated-outcome form instead of the
        # real hosted-fields SDK so the whole flow is testable without LawPay.
        "dev_mode": config.processor == "fake",
        "charge_url": request.build_absolute_uri(request.path.rstrip("/") + "/charge/"),
        **_pay_style(company),
    }
    return render(request, "invoicing/pay/pay.html", context)


@csrf_exempt
@require_http_methods(["POST"])
def pay_charge(request, token):
    if _rate_limited(request, "pay-charge", limit=20, window=300):
        return JsonResponse(
            {"success": False, "error": "Too many attempts. Please wait a moment."},
            status=429,
        )

    # Token gates access in lieu of a session; an invalid/expired token 404s.
    invoice = _resolve_invoice(token)

    try:
        body = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return JsonResponse(
            {"success": False, "error": "Malformed request."}, status=400
        )

    payment_token = (body.get("token") or "").strip()
    method = body.get("method") or ""
    if not payment_token:
        return JsonResponse(
            {"success": False, "error": "Missing payment details."}, status=400
        )

    processor = get_processor()
    # Serialize per-invoice: lock the row, re-check the balance, charge, record —
    # all atomically. A rapid double-submit (or two tabs) then can't both charge,
    # because the second waits for the lock and finds the invoice already paid.
    try:
        with transaction.atomic():
            locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
            # Compute the charge amount/reference directly from the locked row
            # rather than via client_config() — for session-based processors
            # (Confido) client_config() mints a new payment session, so calling
            # it here would orphan one. The client already holds the session it
            # was rendered with (passed back as `payment_token`).
            amount_cents = _to_cents(locked.amount_remaining)
            reference = f"Invoice {locked.id}"
            if amount_cents <= 0:
                already_paid = True
            else:
                already_paid = False
                matter = locked.matter
                result = processor.charge(
                    token=payment_token,
                    amount_cents=amount_cents,
                    reference=reference,
                    method=method,
                    # Scope idempotency to the one-time token, not the invoice:
                    # a retry uses a fresh token (different params), which Stripe
                    # rejects if the key is reused. The row lock + already-paid
                    # check above is the real double-charge guard.
                    idempotency_key=f"{reference}:{payment_token}",
                    metadata={"payer_email": _client_email(matter)},
                    client=_client_info(matter.client if matter else None),
                    matter=_matter_info(matter),
                )
                # Record + apply (provisional PAID for pending ACH); the
                # settlement/return webhook later confirms or reverses it.
                if result.accepted:
                    record_payment(locked, result)
    except ChargeError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=402)

    if already_paid:
        return JsonResponse(
            {"success": False, "error": "This invoice is already paid."}, status=400
        )

    return JsonResponse(
        {
            "success": True,
            "pending": result.is_pending,
            "status": result.status,
            "transaction_id": result.transaction_id,
        }
    )


# --- Matter "catch-up" payment: pay a matter's full open balance ------------


def _resolve_request(token):
    """Return the PaymentRequest for a signed token, or raise Http404."""
    try:
        req_uuid = read_request_token(token, max_age=settings.INVOICE_PAY_LINK_MAX_AGE)
    except signing.SignatureExpired:
        raise Http404("expired")
    except signing.BadSignature:
        raise Http404("invalid")
    return get_object_or_404(PaymentRequest, uuid=req_uuid)


def _balance_config(processor, open_invoices, balance_cents, matter):
    """ClientConfig for a matter balance: reuse the processor's per-invoice config
    (for its publishable key + methods) and override the amount + reference."""
    reference = f"Account balance · Matter {matter.id}"
    if open_invoices:
        base = processor.client_config(open_invoices[0])
        return replace(base, amount_cents=balance_cents, reference=reference)
    # Nothing owed: a stub config — the page shows 'paid in full', no form.
    return ClientConfig(
        processor=processor.name,
        public_key="",
        amount_cents=0,
        reference=reference,
        methods=[],
    )


def balance_pay_page(request, token):
    try:
        pay_request = _resolve_request(token)
    except Http404 as exc:
        if str(exc) == "expired":
            return _unavailable(
                request,
                "This payment link has expired. Please contact us for a new one.",
                status=410,
            )
        return _unavailable(request, "This payment link is invalid.", status=404)

    if pay_request.status == "CANCELED":
        return _unavailable(
            request, "This payment request is no longer active.", status=410
        )

    processor = get_processor()
    charge_cents = request_charge_cents(pay_request)
    from apps.settings.models import Company

    company = Company.objects.first()
    if pay_request.is_trust:
        client = pay_request.client
        config = processor.client_config_for(
            amount_cents=charge_cents,
            reference=f"Trust deposit · Client {client.id}",
            trust=True,
        )
        page_title, subtitle, amount_label = "Trust Deposit", "Trust deposit", "Deposit"
        matter_number, summary_label, summary_value = "", "Client", client.name
    else:
        matter = pay_request.matter
        open_invoices = matter_open_invoices(matter)
        config = _balance_config(processor, open_invoices, charge_cents, matter)
        page_title, subtitle, amount_label = (
            "Pay Account Balance",
            "Account balance",
            "Amount Due",
        )
        matter_number, summary_label, summary_value = (
            matter.id,
            "Open invoices",
            len(open_invoices),
        )
    context = {
        # No single invoice — the page renders in 'balance mode'.
        "invoice": None,
        "page_title": page_title,
        "subtitle": subtitle,
        "amount_label": amount_label,
        "matter_number": matter_number,
        "summary_label": summary_label,
        "summary_value": summary_value,
        "firm_name": company.name if company else "",
        "amount_due": Decimal(charge_cents) / 100,
        "config": config,
        "is_paid": pay_request.status == "PAID" or charge_cents <= 0,
        "dev_mode": config.processor == "fake",
        "charge_url": request.build_absolute_uri(request.path.rstrip("/") + "/charge/"),
        **_pay_style(company),
    }
    return render(request, "invoicing/pay/pay.html", context)


@csrf_exempt
@require_http_methods(["POST"])
def balance_charge(request, token):
    if _rate_limited(request, "pay-charge", limit=20, window=300):
        return JsonResponse(
            {"success": False, "error": "Too many attempts. Please wait a moment."},
            status=429,
        )

    pay_request = _resolve_request(token)

    try:
        body = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return JsonResponse(
            {"success": False, "error": "Malformed request."}, status=400
        )

    payment_token = (body.get("token") or "").strip()
    method = body.get("method") or ""
    if not payment_token:
        return JsonResponse(
            {"success": False, "error": "Missing payment details."}, status=400
        )

    processor = get_processor()
    # Lock the request row to serialize concurrent submits — the second waits and
    # then finds the request already settled. The status + balance recheck under
    # the lock is the double-charge guard (mirrors the per-invoice flow).
    try:
        with transaction.atomic():
            req = PaymentRequest.objects.select_for_update().get(pk=pay_request.pk)
            charge_cents = request_charge_cents(req)
            if req.status != "SENT" or charge_cents <= 0:
                already_paid = True
                # Nothing left to charge while still SENT — settle the request.
                if req.status == "SENT":
                    req.status = "PAID"
                    req.save(update_fields=["status"])
            else:
                already_paid = False
                if req.is_trust:
                    reference = f"Trust deposit · Client {req.client_id}"
                    payer_email = (getattr(req.client, "email", "") or "").strip()
                    client_desc, matter_desc = _client_info(req.client), None
                else:
                    reference = f"Account balance · Matter {req.matter_id}"
                    payer_email = _client_email(req.matter)
                    client_desc = _client_info(getattr(req.matter, "client", None))
                    matter_desc = _matter_info(req.matter)
                result = processor.charge(
                    token=payment_token,
                    amount_cents=charge_cents,
                    reference=reference,
                    idempotency_key=f"request:{req.id}:{payment_token}",
                    method=method,
                    trust=req.is_trust,
                    metadata={"payer_email": payer_email},
                    client=client_desc,
                    matter=matter_desc,
                )
                if result.accepted:
                    if req.is_trust:
                        req.trust_transaction = record_trust_deposit(req.client, result)
                    else:
                        req.payment = record_matter_balance_payment(req.matter, result)
                    req.status = "PAID"
                    req.save(update_fields=["status", "payment", "trust_transaction"])
    except ChargeError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=402)

    if already_paid:
        return JsonResponse(
            {"success": False, "error": "This request has already been paid."},
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "pending": result.is_pending,
            "status": result.status,
            "transaction_id": result.transaction_id,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def processor_webhook(request, processor):
    """Receive a processor webhook. We always 200 quickly (the processor retries
    otherwise) and reconcile out-of-band; the reconciler re-fetches the
    transaction to confirm authenticity, so the raw body is never trusted."""
    if _rate_limited(request, f"webhook-{processor}", limit=240, window=60):
        return HttpResponse(status=429)

    body = request.body.decode("utf-8", "replace")
    # Signed-webhook processors pass their signature header through for
    # verification: Stripe uses `Stripe-Signature`, Confido uses `X-Signature`
    # (HMAC-SHA512 of the raw body). Only one is set per delivery. LawPay doesn't
    # sign and re-fetches instead, so an empty signature is fine there.
    signature = request.headers.get("Stripe-Signature", "") or request.headers.get(
        "X-Signature", ""
    )
    try:
        from django_q.tasks import async_task

        async_task(
            "apps.invoicing.pay.reconcile.reconcile_webhook",
            processor,
            body,
            signature,
        )
    except Exception:
        # If the task queue is unavailable, reconcile inline rather than drop it.
        from apps.invoicing.pay.reconcile import reconcile_webhook

        reconcile_webhook(processor, body, signature)
    return HttpResponse(status=200)
