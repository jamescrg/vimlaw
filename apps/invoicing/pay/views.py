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

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.invoicing.invoices.models import Invoice
from apps.invoicing.pay.recording import record_payment
from apps.invoicing.processors import ChargeError, get_processor
from utils.signing import read_payment_token


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
            config = processor.client_config(locked)
            if config.amount_cents <= 0:
                already_paid = True
            else:
                already_paid = False
                result = processor.charge(
                    token=payment_token,
                    amount_cents=config.amount_cents,
                    reference=config.reference,
                    method=method,
                    # Scope idempotency to the one-time token, not the invoice:
                    # a retry uses a fresh token (different params), which Stripe
                    # rejects if the key is reused. The row lock + already-paid
                    # check above is the real double-charge guard.
                    idempotency_key=f"{config.reference}:{payment_token}",
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


@csrf_exempt
@require_http_methods(["POST"])
def processor_webhook(request, processor):
    """Receive a processor webhook. We always 200 quickly (the processor retries
    otherwise) and reconcile out-of-band; the reconciler re-fetches the
    transaction to confirm authenticity, so the raw body is never trusted."""
    if _rate_limited(request, f"webhook-{processor}", limit=240, window=60):
        return HttpResponse(status=429)

    body = request.body.decode("utf-8", "replace")
    # Stripe signs its webhooks; pass the header through for verification.
    signature = request.headers.get("Stripe-Signature", "")
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
