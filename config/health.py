from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe


def _response(status, http_status=200):
    response = JsonResponse({"status": status}, status=http_status)
    response["Cache-Control"] = "no-store"

    return response


@require_safe
def live(request):
    return _response("ok")


@require_safe
def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return _response("unavailable", http_status=503)

    return _response("ok")
