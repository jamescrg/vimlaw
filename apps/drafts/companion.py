"""Server side of the LibreOffice companion extension.

The extension (apps/drafts/companion_src, downloaded as a personalized .oxt
via companion_oxt) runs inside the user's LibreOffice Writer, pairs the open
document with its draft link by filename, and polls this API:

    GET  sessions/              the token user's draft links, newest first
    POST <link>/hello/          register + push the document (odt_b64)
    GET  <link>/ops/            pick up the next pending edit round
    POST <link>/rounds/<id>/    report the round's outcome (+ document)

Every call refreshes companion_seen; while that is fresh the chat worker
routes edit rounds here (chat._apply_via_companion). Document pushes are ODT
bytes, converted server-side to a Markdown facsimile (the accepted view,
tables included), which becomes the AI's draft context.

Auth is a per-user key in the X-Kosmos-Token header (CompanionToken). These
endpoints are CSRF-exempt: the client is urllib inside LibreOffice, not a
browser with cookies. An unlinked draft answers 404, which tells the
extension to stop polling.
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

from apps.drafts.models import CompanionRound, CompanionToken, DraftLink
from apps.drive import convert

logger = logging.getLogger(__name__)

COMPANION_SRC = Path(__file__).resolve().parent / "companion_src"
EXTENSION_VERSION = "0.3.0"


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


def _get_link(request, link_id):
    return get_object_or_404(
        DraftLink.objects.select_related("conversation__matter"),
        pk=link_id,
        conversation__user=request.companion_user,
    )


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _store_document(link, payload):
    """Decode a pushed ODT and store its Markdown facsimile as the draft
    text on the link AND its siblings (other conversations linking the same
    file read the same live document). Fails soft: a bad push never breaks
    the poll loop."""
    odt_b64 = payload.get("odt_b64")
    if not odt_b64:
        return
    try:
        odt_bytes = base64.b64decode(odt_b64)
        text = convert.to_markdown(odt_bytes, ".odt")
    except Exception:
        logger.exception("Companion document push failed for link %s", link.id)
        return
    now = timezone.now()
    link.sibling_links().update(doc_text=text, doc_text_at=now)
    link.doc_text = text
    link.doc_text_at = now


def _touch(link):
    link.companion_seen = timezone.now()
    link.save(update_fields=["companion_seen"])


@companion_auth
@require_http_methods(["GET"])
def api_sessions(request):
    """The token user's draft links, newest first."""
    links = DraftLink.objects.filter(
        conversation__user=request.companion_user
    ).select_related("conversation__matter")
    return JsonResponse(
        {
            "sessions": [
                {
                    "id": link.id,
                    "name": link.name,
                    "matter": link.conversation.matter.name
                    if link.conversation.matter
                    else "",
                }
                for link in links
            ]
        }
    )


@companion_auth
@require_http_methods(["POST"])
def api_hello(request, link_id):
    """Register the companion (and on later calls, refresh the document)."""
    link = _get_link(request, link_id)
    _store_document(link, _json_body(request))
    _touch(link)
    logger.info("Companion connected to draft link %s", link.id)
    matter = link.conversation.matter
    return JsonResponse(
        {
            "status": "drafting",
            "name": link.name,
            "matter": matter.name if matter else "",
        }
    )


@companion_auth
@require_http_methods(["GET"])
def api_ops(request, link_id):
    """Deliver the oldest undelivered pending round, at most once.

    A round is never redelivered: if the extension dies mid-application the
    chat worker's wait expires it and the user simply asks again. Redelivery
    would risk applying the same edits twice to the live document.
    """
    link = _get_link(request, link_id)
    _touch(link)
    round_ = (
        CompanionRound.objects.filter(
            link__in=link.sibling_links(),
            status="pending",
            delivered_at__isnull=True,
        )
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
def api_result(request, link_id, round_id):
    """Record a round's outcome and the resulting document."""
    link = _get_link(request, link_id)
    round_ = get_object_or_404(
        CompanionRound, pk=round_id, link__in=link.sibling_links()
    )
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
    _store_document(link, payload)
    _touch(link)
    return JsonResponse({"status": "drafting"})


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
