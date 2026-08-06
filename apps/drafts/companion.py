"""Server side of the LibreOffice companion extension.

The extension (apps/drafts/companion_src, downloaded as a personalized .oxt
via companion_oxt) runs inside the user's LibreOffice Writer, pairs the open
document with its active drafting session, and polls this API:

    GET  sessions/                 active drafting sessions for the token user
    POST <session>/hello/          register + push the document (odt_b64)
    GET  <session>/ops/            pick up the next pending edit round
    POST <session>/rounds/<id>/    report the round's outcome (+ document)

Every call refreshes companion_seen; while that is fresh the chat worker
routes edit rounds here (chat._apply_via_companion) instead of the headless
applier. Document pushes are ODT bytes, converted server-side to the same
Markdown facsimile the headless pipeline produces, so the AI reads the
accepted view of the live document, tables included.

Auth is a per-user key in the X-Kosmos-Token header (CompanionToken). These
endpoints are CSRF-exempt: the client is urllib inside LibreOffice, not a
browser with cookies.
"""

import base64
import io
import json
import logging
import zipfile
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.drafts.models import CompanionRound, CompanionToken, DraftSession
from apps.drive import convert

logger = logging.getLogger(__name__)

COMPANION_SRC = Path(__file__).resolve().parent / "companion_src"
EXTENSION_VERSION = "0.2.0"


def companion_auth(view):
    """Token auth for extension endpoints; sets request.companion_user."""

    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        key = request.headers.get("X-Kosmos-Token", "")
        token = (
            CompanionToken.objects.select_related("user").filter(key=key).first()
            if key
            else None
        )
        if token is None or not token.user.is_active:
            return JsonResponse({"error": "invalid token"}, status=401)
        request.companion_user = token.user
        return view(request, *args, **kwargs)

    return wrapper


def _get_session(request, session_id):
    return get_object_or_404(
        DraftSession.objects.select_related("matter"),
        pk=session_id,
        user=request.companion_user,
    )


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _store_document(session, payload):
    """Decode a pushed ODT and store its Markdown facsimile as the session's
    companion text. Fails soft: a bad push never breaks the poll loop."""
    odt_b64 = payload.get("odt_b64")
    if not odt_b64:
        return
    try:
        odt_bytes = base64.b64decode(odt_b64)
        session.companion_text = convert.to_markdown(odt_bytes, ".odt")
        session.companion_text_at = timezone.now()
    except Exception:
        logger.exception("Companion document push failed for session %s", session.id)


def _touch(session, with_text=False):
    session.companion_seen = timezone.now()
    fields = ["companion_seen"]
    if with_text:
        fields += ["companion_text", "companion_text_at"]
    session.save(update_fields=fields)


@companion_auth
@require_http_methods(["GET"])
def api_sessions(request):
    """The token user's active drafting sessions, newest first."""
    sessions = DraftSession.objects.filter(
        user=request.companion_user, status="drafting"
    ).select_related("matter")
    return JsonResponse(
        {
            "sessions": [
                {"id": s.id, "name": s.name, "matter": s.matter.name} for s in sessions
            ]
        }
    )


@companion_auth
@require_http_methods(["POST"])
def api_hello(request, session_id):
    """Register the companion (and on later calls, refresh the document)."""
    session = _get_session(request, session_id)
    if session.status != "drafting":
        return JsonResponse({"status": session.status}, status=409)
    _store_document(session, _json_body(request))
    _touch(session, with_text=True)
    logger.info("Companion connected to session %s", session.id)
    return JsonResponse(
        {"status": "drafting", "name": session.name, "matter": session.matter.name}
    )


@companion_auth
@require_http_methods(["GET"])
def api_ops(request, session_id):
    """Deliver the oldest undelivered pending round, at most once.

    A round is never redelivered: if the extension dies mid-application the
    chat worker's wait expires it and the user simply asks again. Redelivery
    would risk applying the same edits twice to the live document.
    """
    session = _get_session(request, session_id)
    _touch(session)
    if session.status != "drafting":
        return JsonResponse({"status": session.status, "round": None})
    round_ = (
        session.companion_rounds.filter(status="pending", delivered_at__isnull=True)
        .order_by("created_at")
        .first()
    )
    if round_ is None:
        return JsonResponse({"status": "drafting", "round": None})
    round_.delivered_at = timezone.now()
    round_.save(update_fields=["delivered_at"])
    return JsonResponse(
        {"status": "drafting", "round": {"id": round_.id, "edits": round_.edits}}
    )


@companion_auth
@require_http_methods(["POST"])
def api_result(request, session_id, round_id):
    """Record a round's outcome and the resulting document."""
    session = _get_session(request, session_id)
    round_ = get_object_or_404(CompanionRound, pk=round_id, session=session)
    payload = _json_body(request)
    if round_.status == "pending":
        if payload.get("ok"):
            round_.status = "applied"
            round_.result = payload.get("results") or []
        else:
            round_.status = "failed"
            round_.error = str(payload.get("error") or "unknown companion error")
            index = payload.get("edit_index")
            round_.edit_index = index if isinstance(index, int) else None
        round_.save()
    _store_document(session, payload)
    _touch(session, with_text=True)
    return JsonResponse({"status": session.status})


def companion_oxt(request):
    """Build and serve the personalized .oxt (login required, applied in
    urls.py via the standard decorator on the wrapping view).

    The extension source is zipped as-is with one generated member:
    config.json carrying this server's URL and the requesting user's token.
    Building on demand keeps the download in lockstep with deployed code.
    """
    token = CompanionToken.for_user(request.user)
    server = settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(COMPANION_SRC.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(COMPANION_SRC).as_posix())
        archive.writestr(
            "config.json",
            json.dumps(
                {
                    "server": server,
                    "token": token.key,
                    "version": EXTENSION_VERSION,
                }
            ),
        )
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename="kosmos-companion.oxt",
        content_type="application/vnd.openofficeorg.extension",
    )
