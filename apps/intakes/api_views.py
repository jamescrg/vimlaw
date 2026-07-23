import json
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.intakes.models import Intake, Note
from apps.matters.models import PracticeArea

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
@require_http_methods(["POST"])
def receive_intake(request):
    """
    API endpoint receiving the website's client intake questionnaire.
    Maps the basic contact details onto an Intake and files the full
    report as a note with no user, typed "Client Form" to flag it as
    self-submitted by the prospective client. A follow-up payload may
    carry intake_id to attach a supplement note to the same intake.
    """
    try:
        data = json.loads(request.body)

        full_name = data.get("full_name", "")
        report = data.get("report", "")
        intake_id = data.get("intake_id")

        if not report or not (full_name or intake_id):
            return JsonResponse(
                {"success": False, "error": "Missing required fields"}, status=400
            )

        intake = None
        if intake_id:
            intake = Intake.objects.filter(id=intake_id).first()

        if intake is None:
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
