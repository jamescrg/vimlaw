"""Intake-from-email: Mailgun inbound-route webhook and AI extraction.

The attorney forwards a prospective client's email (or a Zoom voicemail
transcription) to the intake address; Mailgun's route POSTs the parsed
message here. After signature, allowlist, and duplicate checks the message
is stored as an InboundEmail row and handed to a worker, which asks the AI
to extract intake fields and creates an Intake plus a first Note holding
the original message text. A follow-up whose extracted email or phone
matches an existing intake is logged as a note on that intake instead of
opening a duplicate. An intake is always created for an accepted message,
even when extraction fails.
"""

import hashlib
import hmac
import json
import logging
import re
import time
from email.utils import parseaddr

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Replace
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.accounts.models import CustomUser
from apps.intakes.forms import IntakeForm
from apps.intakes.models import InboundEmail, Intake, Note
from apps.matters.models import PracticeArea
from config.helpers import normalize_phone

logger = logging.getLogger(__name__)

# Mailgun re-signs each delivery attempt with a fresh timestamp, so a
# tight replay window is safe.
SIGNATURE_MAX_AGE = 300

# Cap what is sent to the AI; forwarded chains can drag in huge histories.
EXTRACTION_TEXT_LIMIT = 50_000

VALID_SOURCES = {value for value, _ in IntakeForm.Meta.SOURCES}

# Lines that begin the forwarded portion in the major mail clients;
# everything above the earliest one is the forwarder's own wrapper
# (signature, "FW:" chrome), not the client's message.
FORWARD_MARKERS = [
    re.compile(r"^-{4,}\s*Forwarded message\s*-{4,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Begin forwarded message:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^-{3,}\s*Original Message\s*-{3,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^_{8,}\s*$", re.MULTILINE),
]

EXTRACTION_PROMPT = """You extract prospective-client intake details from an email forwarded to a
law firm's intake mailbox. The message is one of: (a) an email inquiry from
a prospective client, forwarded by the attorney, or (b) a Zoom voicemail
transcription email. The forwarding attorney is NOT the prospective client;
look inside the forwarded/quoted content or the transcription for the
client's details.

Return ONLY a JSON object with this exact shape:
{{
  "kind": "email" | "voicemail",
  "name": "<prospective client's full name, or null>",
  "phone": "<client's phone number, or null>",
  "email": "<client's email address, or null>",
  "address": "<client's mailing address, or null>",
  "disputed_property": "<address or description of the disputed property if different from the client's address, or null>",
  "value": <approximate dollar value of the disputed property or dispute as an integer, or null>,
  "practice_area": "<one of: {area_names}, or null>",
  "source": "<one of: Unknown, Internet, Agent, Attorney - Internal, Attorney - External, Other>",
  "summary": "<1-2 sentence summary of what the person wants>",
  "transcript": "<voicemail only: the transcription text, or null for emails>",
  "importance": <integer 1-7, or null>,
  "importance_rationale": "<2-4 sentences explaining the rating, or null>"
}}

Rules:
- "kind" is "voicemail" only when the message is a voicemail transcription
  (e.g. Zoom Phone); otherwise "email".
- Use null for anything not stated in the message; never invent values.
- "practice_area" must be copied exactly from the list above, or null if no
  clear fit.
- "source": "Internet" if they found the firm online, "Attorney - External"
  if referred by an outside attorney, "Agent" if referred by a real estate
  agent or broker; otherwise "Unknown" unless the message clearly says.
- "transcript": when the message is a voicemail transcription, copy the
  caller's transcribed words EXACTLY as they appear, word for word - no
  paraphrasing, no corrections, no added punctuation. Do not include the
  provider's surrounding text (caller-ID lines, links, footers). Null when
  the message is an email.
- "importance": how promising this intake looks for the firm, on the firm's
  1-7 scale (7 Highest, 6 Higher, 5 High, 4 Normal, 3 Low, 2 Lower,
  1 Lowest). Judge the substance, not the amount of detail: raise above 4
  only on concrete positive signals (clearly fits the firm's practice
  areas, meaningful amount in dispute, an apparently viable claim, genuine
  urgency); lower below 4 only on concrete negative signals (outside the
  practice areas, no real legal dispute, apparently unviable position,
  signs of an undesirable engagement). When the message is too thin to
  judge either way, use null and the intake keeps its normal rating.
- "importance_rationale": required whenever "importance" is anything other
  than null or 4 - explain in 2-4 sentences why this intake deserves a
  higher or lower rating. Null otherwise.
- Return ONLY the JSON object, no other text, no markdown fences."""


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


def _verify_mailgun_signature(post):
    """Check Mailgun's HMAC over timestamp+token. An empty signing key means
    verification is not enforced, so the webhook can be deployed before the
    key is configured (KOSMOS_SEAM_KEY precedent)."""
    key = settings.MAILGUN_WEBHOOK_SIGNING_KEY
    if not key:
        return True

    timestamp = post.get("timestamp", "")
    token = post.get("token", "")
    signature = post.get("signature", "")
    try:
        if abs(time.time() - float(timestamp)) > SIGNATURE_MAX_AGE:
            return False
    except (TypeError, ValueError):
        return False

    expected = hmac.new(
        key.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@csrf_exempt
@require_http_methods(["POST"])
def mailgun_inbound(request):
    """Receive a message from the Mailgun intake route. Accepted messages are
    stored and processed out-of-band; a fast 200 keeps Mailgun from retrying.
    Rejections are deliberate about status: 403 makes Mailgun retry (recovers
    a misconfigured signing key), 200 is a permanent intentional drop."""
    if _rate_limited(request, "mailgun-inbound", limit=60, window=60):
        return HttpResponse(status=429)

    if not _verify_mailgun_signature(request.POST):
        return HttpResponse(status=403)

    # The Mailgun route is shared (route-quota 1): it also relays billing
    # replies and posts to prod and dev alike, so only mail addressed to
    # THIS instance's intake mailbox becomes an intake here
    recipient = request.POST.get("recipient", "")
    local_part = recipient.split("@")[0].strip().lower()
    if local_part != settings.INTAKE_INBOUND_RECIPIENT:
        return HttpResponse(status=200)

    # The forwarding sender must be a firm user; the prospective client's
    # details live inside the forwarded body, not the envelope. Anything
    # else is spam sent straight to the intake address: drop unstored.
    from_header = request.POST.get("from") or request.POST.get("sender") or ""
    _, sender_email = parseaddr(from_header)
    user = CustomUser.objects.filter(email__iexact=sender_email, is_active=True).first()
    if user is None:
        return HttpResponse(status=200)

    subject = request.POST.get("subject", "")
    body_plain = request.POST.get("body-plain", "")

    message_id = (
        request.POST.get("Message-Id") or request.POST.get("message-id") or ""
    ).strip("<> ")
    if not message_id:
        fingerprint = f"{sender_email}{subject}{body_plain}".encode()
        message_id = "sha256:" + hashlib.sha256(fingerprint).hexdigest()

    inbound, created = InboundEmail.objects.get_or_create(
        message_id=message_id[:255],
        defaults={
            "sender": sender_email[:255],
            "recipient": request.POST.get("recipient", "")[:255],
            "subject": subject[:500],
            "body_plain": body_plain,
            "stripped_text": request.POST.get("stripped-text", ""),
        },
    )
    if not created:
        # A Mailgun retry of a delivery we already accepted
        return HttpResponse(status=200)

    try:
        from django_q.tasks import async_task

        async_task("apps.intakes.inbound.process_inbound_email", inbound.id)
    except Exception:
        # If the task queue is unavailable, process inline rather than drop it.
        process_inbound_email(inbound.id)
    return HttpResponse(status=200)


def _kosmos_user():
    """The system identity that authors AI-created notes. A real (inactive,
    login-less) user rather than None so the note renders an author and the
    new-note badge fires for every human viewer - notes by the forwarding
    user would read as already seen by the person most likely to review the
    intake. is_active=False keeps it out of the sender allowlist, the AI
    team roster, and the digest."""
    user, created = CustomUser.objects.get_or_create(
        username="kosmos",
        defaults={"is_active": False, "is_attorney": False, "title": "AI Assistant"},
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


def _match_existing_intake(email_addr, phone):
    """A follow-up from a known prospective client lands on their existing
    intake rather than opening a duplicate. Match on the extracted email
    first, then on a 10-digit phone comparison (digits against digits, the
    search_intakes idiom, since phones are stored however they were typed).
    The most recent matching intake wins."""
    if email_addr:
        match = (
            Intake.objects.filter(email__iexact=email_addr)
            .order_by("-date", "-id")
            .first()
        )
        if match:
            return match

    digits = re.sub(r"\D", "", phone or "")[-10:]
    if len(digits) == 10:
        phone_digits = F("phone")
        for mark in ("-", " ", "(", ")", "."):
            phone_digits = Replace(phone_digits, Value(mark), Value(""))
        return (
            Intake.objects.annotate(phone_digits=phone_digits)
            .filter(phone_digits__contains=digits)
            .order_by("-date", "-id")
            .first()
        )
    return None


def _strip_forward_prelude(text):
    """Drop the forwarder's signature/preamble above the first recognized
    forwarded-message marker; the marker and the From/Date block below it
    stay, since they identify the client. A client whose marker isn't
    recognized keeps the full text — noisy beats lost."""
    positions = [
        match.start() for marker in FORWARD_MARKERS if (match := marker.search(text))
    ]
    return text[min(positions) :] if positions else text


def _extract_intake_fields(subject, text):
    """One AI call mapping the message onto intake fields. Returns
    (data, error); any failure returns ({}, reason) so the caller can
    still create a fallback intake from the raw message."""
    from apps.case.ai.gemini_client import send_to_gemini

    area_names = ", ".join(
        PracticeArea.objects.filter(is_active=True).values_list("name", flat=True)
    )
    system_prompt = EXTRACTION_PROMPT.format(area_names=area_names)
    message = f"Subject: {subject}\n\n{text}"

    try:
        response, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": message}]
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned.strip())
        if not isinstance(data, dict):
            raise ValueError("AI response is not a JSON object")
        return data, None
    except Exception as exc:
        logger.exception("Inbound email extraction failed")
        return {}, str(exc)


def process_inbound_email(inbound_email_id):
    """Worker task: extract fields from a stored inbound message and create
    the Intake and its first Note. Idempotent — a row that already has an
    intake is left alone."""
    inbound = InboundEmail.objects.filter(id=inbound_email_id).first()
    if inbound is None or inbound.intake_id:
        return

    # body-plain over stripped-text: for a forwarded message the client's
    # content is usually the quoted part that stripping removes
    text = (inbound.body_plain or inbound.stripped_text or "").strip()
    data, error = _extract_intake_fields(inbound.subject, text[:EXTRACTION_TEXT_LIMIT])

    phone, _ = normalize_phone((data.get("phone") or "").strip())
    # Voicemail transcripts often arrive all-lowercase; title-case the name
    name = (data.get("name") or "").strip().title()
    if not name and phone:
        name = f"Unknown caller {phone}"
    if not name:
        name = (inbound.subject or "").strip() or "Unknown inquiry"

    practice_area = None
    if data.get("practice_area"):
        practice_area = PracticeArea.objects.filter(
            is_active=True, name__iexact=str(data["practice_area"]).strip()
        ).first()

    source = data.get("source")
    if source not in VALID_SOURCES:
        source = "Unknown"

    try:
        value = int(data.get("value"))
    except (TypeError, ValueError):
        value = None

    # 1-7 scale, 4 = Normal. The AI rates only on concrete signals; a thin
    # message comes back null and keeps the model default.
    try:
        importance = min(max(int(data.get("importance")), 1), 7)
    except (TypeError, ValueError):
        importance = None
    rationale = (data.get("importance_rationale") or "").strip()

    # The AI reads the full text (the forwarder's commentary above the
    # marker can inform the summary), but the note keeps only the client's
    # message. For emails that's the marker-stripped text, verbatim — no AI
    # rewriting of client-authored words. For voicemails the AI lifts the
    # transcript out of the provider's notification chrome; the text is
    # machine-generated anyway and the untouched original stays on the
    # InboundEmail row.
    note_text = _strip_forward_prelude(text).strip()
    if data.get("kind") == "voicemail" and (data.get("transcript") or "").strip():
        note_text = data["transcript"].strip()
    summary = (data.get("summary") or "").strip()
    details = (
        f"**AI summary:** {summary}\n\n---\n\n{note_text}" if summary else note_text
    )
    note_type = "VM In" if data.get("kind") == "voicemail" else "Email In"

    now = timezone.localtime()
    kosmos = _kosmos_user()

    # A follow-up from a known caller is logged on their existing intake
    # instead of opening a duplicate. The intake's own fields, importance,
    # and assessment are left alone - reassessing is a click away.
    matched = _match_existing_intake((data.get("email") or "").strip(), phone)
    if matched:
        with transaction.atomic():
            Note.objects.create(
                intake=matched,
                user=kosmos,
                date=now.date(),
                time=now.time(),
                type=note_type,
                details=details,
            )
            if matched.status == "Unresponsive":
                # The client resurfacing is exactly what this status was
                # waiting on; reopening also relights the new-note badge.
                # (Pending stays put: it means the intake is being migrated
                # to a client, not that we're waiting on the caller.)
                matched.status = "Open"
                matched.save()
            inbound.intake = matched
            inbound.status = "failed" if error else "processed"
            inbound.error = error or ""
            inbound.save()
        return

    # A rating away from Normal seeds the Assessment tab with the reasoning
    seeds_assessment = importance is not None and importance != 4 and rationale

    with transaction.atomic():
        intake = Intake.objects.create(
            name=name[:100],
            date=now.date(),
            status="Open",
            source=source,
            phone=(phone or "").strip()[:50] or None,
            email=(data.get("email") or "").strip()[:100] or None,
            address=(data.get("address") or "").strip()[:255] or None,
            disputed_property=(data.get("disputed_property") or "").strip()[:255]
            or None,
            value=value,
            practice_area=practice_area,
            importance=importance or 4,
            assessment=rationale if seeds_assessment else "",
            assessed_at=now if seeds_assessment else None,
        )
        Note.objects.create(
            intake=intake,
            user=kosmos,
            date=now.date(),
            time=now.time(),
            type=note_type,
            details=details,
        )
        inbound.intake = intake
        inbound.status = "failed" if error else "processed"
        inbound.error = error or ""
        inbound.save()
