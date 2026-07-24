import json
import re
from datetime import datetime
from functools import wraps

from django.conf import settings
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Replace
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.intakes.models import Intake, Note
from apps.matters.models import PracticeArea


def seam_protected(view):
    """Requires X-Seam-Key when KOSMOS_SEAM_KEY is configured; when the
    env var is unset, auth is not enforced so a one-sided deploy can't
    brick the seam. Enforcement begins when both envs carry the secret."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        key = settings.KOSMOS_SEAM_KEY
        if key and request.headers.get("X-Seam-Key") != key:
            return JsonResponse({"success": False, "error": "Unauthorized"}, status=403)
        return view(request, *args, **kwargs)

    return wrapper


# The website questionnaire's dispute natures, mapped onto the firm's
# practice areas (rows seeded by matters migration 0048)
DISPUTE_TO_PRACTICE_AREA = {
    "boundary": "Boundary",
    "easement": "Easement",
    "quiet_title": "Title",
    "contract": "Purchase / Sale",
    "hoa": "HOA",
    "landlord": "LLT-L",
    "tenant": "LLT-T",
    "construction": "Construction",
    "fraud": "Fraud",
    "commercial": "Commercial",
    "collections": "Collections",
    "other": "General",
}


@csrf_exempt
@require_http_methods(["POST"])
@seam_protected
def receive_inquiry(request):
    """
    API endpoint to receive inquiry data from external sources.
    Returns JSON response with success/failure status.
    """
    try:
        data = json.loads(request.body)

        full_name = data.get("full_name", "")
        phone_number = data.get("phone_number", "")
        email = data.get("email", "")
        summary = data.get("summary", "")

        if not all([full_name, phone_number, email, summary]):
            return JsonResponse(
                {"success": False, "error": "Missing required fields"}, status=400
            )

        intake = Intake.objects.create(
            name=full_name,
            phone=phone_number,
            date=datetime.now().date(),
            status="Open",
            email=email,
        )

        Note.objects.create(
            date=datetime.now().date(),
            time=datetime.now().time(),
            intake=intake,
            type="Email In",
            details=summary,
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Inquiry received successfully",
                "intake_id": intake.id,
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON data"}, status=400
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@seam_protected
def search_intakes(request):
    """
    The website office's window into the intake roster: it searches
    here before minting client-form links, so an intake logged from a
    phone call is found and attached rather than duplicated. A blank
    query lists the open roster — the office's landing view, one click
    from attaching. Numeric queries match the intake number exactly or
    a phone fragment; text queries match name or phone.
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        matches = Q(status="Open")
    else:
        # Phones are stored however they were typed; compare digits to
        # digits so "5550122" finds "404-555-0122"
        q_digits = re.sub(r"\D", "", q)
        matches = Q(id=int(q)) if q.isdigit() else Q(name__icontains=q)
        if q_digits:
            matches |= Q(phone_digits__contains=q_digits)

    phone_digits = models.F("phone")
    for mark in ("-", " ", "(", ")", "."):
        phone_digits = Replace(phone_digits, Value(mark), Value(""))
    intakes = (
        Intake.objects.annotate(phone_digits=phone_digits)
        .filter(matches)
        .select_related("practice_area")
        .order_by("-id")[:20]
    )
    results = [
        {
            "id": intake.id,
            "name": intake.name,
            "phone": intake.phone or "",
            "email": intake.email or "",
            "status": intake.status,
            "date": intake.date.isoformat() if intake.date else "",
            "practice_area": (
                intake.practice_area.name if intake.practice_area else ""
            ),
        }
        for intake in intakes
    ]
    return JsonResponse({"success": True, "results": results})


@csrf_exempt
@require_http_methods(["POST"])
@seam_protected
def receive_intake(request):
    """
    API endpoint receiving the website's client intake questionnaire.
    Maps the basic contact details onto an Intake and files the full
    report as a note with no user, typed "Client Form" to flag it as
    self-submitted by the prospective client. A follow-up payload may
    carry intake_id to attach a note to the same intake, and note_id
    to update a previously filed note in place — the website's forms
    stay editable after submission, and each resubmission replaces its
    original note rather than adding another.
    """
    try:
        data = json.loads(request.body)

        full_name = data.get("full_name", "")
        report = data.get("report", "")
        intake_id = data.get("intake_id")
        note_id = data.get("note_id")

        if not report or not (full_name or intake_id):
            return JsonResponse(
                {"success": False, "error": "Missing required fields"}, status=400
            )

        intake = None
        if intake_id:
            intake = Intake.objects.filter(id=intake_id).first()

        if intake is None:
            # Create-fallback for legacy unbound website intakes only.
            # Since the website's office attaches to existing Kosmos
            # intakes (intake records are born here, not there), every
            # new push carries intake_id and this branch should be
            # unreachable; it stays for old cl rows without a binding.
            area_name = DISPUTE_TO_PRACTICE_AREA.get(data.get("dispute_nature", ""))
            practice_area = (
                PracticeArea.objects.filter(name=area_name).first()
                if area_name
                else None
            )
            intake = Intake.objects.create(
                name=full_name,
                phone=data.get("phone_number", ""),
                email=data.get("email", ""),
                address=data.get("address", "")[:255],
                disputed_property=data.get("disputed_property", "")[:255],
                practice_area=practice_area,
                date=datetime.now().date(),
                status="Open",
                source="Internet",
            )

        note = None
        if note_id:
            # An update edits the original note; a stale id falls
            # through and files a fresh note instead
            note = Note.objects.filter(id=note_id, intake=intake).first()
        if note is not None:
            note.details = report
            note.save()
        else:
            note = Note.objects.create(
                date=datetime.now().date(),
                time=datetime.now().time(),
                intake=intake,
                user=None,
                type="Client Form",
                details=report,
            )

        return JsonResponse(
            {
                "success": True,
                "message": "Intake received successfully",
                "intake_id": intake.id,
                "note_id": note.id,
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON data"}, status=400
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
