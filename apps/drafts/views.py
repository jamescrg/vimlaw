"""Views for the Drafts case tab and the standalone drafting window.

The window is a split pane: the shared AI chat machinery on the left
(case/ai templates + the case:ai-status polling cycle), and a per-version
PDF preview (pdf.js) on the right. The right pane re-syncs after every
message swap via the ?have= short-circuit: the client sends the version it
is showing and gets 204 (no swap) when nothing changed.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.case.ai.models import Message
from apps.case.ai.views import VALID_LLMS
from apps.case.views import get_matter_from_url, set_last_tab
from apps.drafts import chat, services
from apps.drafts.models import DraftSession, DraftVersion
from apps.drive import google

logger = logging.getLogger(__name__)


def get_drafts_data(request, matter, matter_id):
    return {
        "sessions": matter.draft_sessions.select_related("conversation").all(),
        "drive_ready": bool(matter.drive_folder) and google.check_credentials(),
    }


@login_required
def drafts_index(request, matter_id):
    """Main drafts view (the case Drafts tab)."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "drafts")
    context = {
        "app": "matters",
        "subapp": "drafts",
        "matter": matter,
        "matters": matters,
    } | get_drafts_data(request, matter, matter_id)
    return render(request, "case/drafts/main.html", context)


@login_required
def drafts_list(request, matter_id):
    """List partial for HTMX refreshes."""
    matter, matters = get_matter_from_url(request, matter_id)
    context = {"matter": matter, "matters": matters} | get_drafts_data(
        request, matter, matter_id
    )
    return render(request, "case/drafts/list.html", context)


@login_required
def draft_picker(request, matter_id):
    """The ODT file list for starting a session (fetched on demand: it
    walks the matter's Drive folder)."""
    matter, _ = get_matter_from_url(request, matter_id)
    return render(
        request,
        "case/drafts/picker.html",
        {"matter": matter, "files": services.list_matter_odt_files(matter)},
    )


@login_required
def draft_start(request, matter_id):
    """Open (or resume) a session for a Drive file, then show the window.

    A GET so the picker can open it directly in a new tab (window.open from
    an async response would be popup-blocked). Idempotent per file: an
    existing live session for the same Drive file is resumed, not duplicated.
    """
    matter, _ = get_matter_from_url(request, matter_id)
    drive_file_id = request.GET.get("file", "")
    if not drive_file_id:
        return HttpResponse("Missing file parameter.", status=400)

    session = matter.draft_sessions.filter(
        drive_file_id=drive_file_id, status="drafting"
    ).first()
    if session is None:
        try:
            session = services.create_session(matter, drive_file_id, request.user)
        except services.DraftError as exc:
            return render(
                request,
                "case/drafts/window-error.html",
                {"matter": matter, "error": str(exc)},
                status=502,
            )
    return redirect("case:draft-window", session_id=session.id)


@login_required
def draft_window(request, session_id):
    """The standalone drafting window (chat left, preview right)."""
    session = get_object_or_404(
        DraftSession.objects.select_related("matter", "conversation"), pk=session_id
    )
    conversation = session.conversation
    messages = (
        conversation.messages.select_related("user").all() if conversation else []
    )
    return render(
        request,
        "case/drafts/window.html",
        {
            "session": session,
            "matter": session.matter,
            "conversation": conversation,
            "messages": messages,
            "versions": session.versions.all(),
            "latest": session.current_version,
        },
    )


@login_required
@require_http_methods(["POST"])
def draft_send(request, session_id):
    """Mirror of the case send_message cycle, session-scoped."""
    session = get_object_or_404(
        DraftSession.objects.select_related("matter", "conversation"), pk=session_id
    )
    conversation = session.conversation
    user_message = request.POST.get("message", "").strip()
    if not user_message or conversation is None:
        return HttpResponse(status=400)
    if session.status != "drafting":
        return HttpResponse("This session has been settled.", status=409)

    llm = request.POST.get("llm", "")
    if llm in VALID_LLMS and llm != conversation.llm:
        conversation.llm = llm
        conversation.save(update_fields=["llm"])

    Message.objects.create(
        conversation=conversation,
        role="user",
        content=user_message,
        user=request.user,
    )
    chat.start_worker(conversation, session, request.user)

    return render(
        request,
        "case/ai/messages.html",
        {
            "messages": conversation.messages.all(),
            "conversation": conversation,
            "session": session,
            "is_processing": True,
        },
    )


@login_required
def draft_messages(request, session_id):
    """Refresh target for the messagesUpdated trigger."""
    session = get_object_or_404(DraftSession, pk=session_id)
    conversation = session.conversation
    messages = (
        conversation.messages.select_related("user").all() if conversation else []
    )
    return render(
        request,
        "case/ai/messages.html",
        {"messages": messages, "conversation": conversation, "session": session},
    )


@login_required
def draft_pane(request, session_id):
    """The right pane: version pills, actions, PDF preview.

    ?have=<seq> short-circuits to 204 when the client already shows the
    latest version, so the post-message sync is free when no edits landed.
    """
    session = get_object_or_404(DraftSession, pk=session_id)
    latest = session.current_version
    have = request.GET.get("have")
    if have is not None and latest is not None and have == str(latest.seq):
        return HttpResponse(status=204)
    return render(
        request,
        "case/drafts/pane.html",
        {"session": session, "versions": session.versions.all(), "latest": latest},
    )


@login_required
@require_http_methods(["POST"])
def draft_publish(request, session_id):
    session = get_object_or_404(DraftSession, pk=session_id)
    accept = request.POST.get("accept") == "1"
    try:
        services.publish_session(session, accept=accept)
    except services.DraftError as exc:
        logger.warning("Publish refused for session %s: %s", session_id, exc)
    return _pane_response(request, session)


@login_required
@require_http_methods(["POST"])
def draft_discard(request, session_id):
    session = get_object_or_404(DraftSession, pk=session_id)
    try:
        services.abandon_session(session)
    except services.DraftError as exc:
        logger.warning("Discard refused for session %s: %s", session_id, exc)
    return _pane_response(request, session)


def _pane_response(request, session):
    response = render(
        request,
        "case/drafts/pane.html",
        {
            "session": session,
            "versions": session.versions.all(),
            "latest": session.current_version,
        },
    )
    response["HX-Trigger"] = "draftsChanged"
    return response


@login_required
def draft_version_pdf(request, version_id):
    """Serve a version's PDF inline for the pdf.js iframe (same reasoning
    as case:serve — streaming through Django avoids S3 CORS)."""
    version = get_object_or_404(DraftVersion, pk=version_id)
    if not version.pdf_file:
        return HttpResponse("This version's preview has been cleaned up.", status=410)
    try:
        handle = version.pdf_file.open("rb")
    except FileNotFoundError:
        # Row survived but the blob is gone (on dev, the nightly media mirror
        # prunes drafts/* until the feature ships to prod).
        return HttpResponse("This version's preview file is missing.", status=410)
    response = FileResponse(handle, content_type="application/pdf")
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
def draft_version_odt(request, version_id):
    """Download a version's redlined ODT."""
    version = get_object_or_404(
        DraftVersion.objects.select_related("session"), pk=version_id
    )
    if not version.odt_file:
        return HttpResponse("This version's file has been cleaned up.", status=410)
    stem = version.session.name.rsplit(".", 1)[0]
    label = "final" if version.is_accepted else "redline"
    try:
        handle = version.odt_file.open("rb")
    except FileNotFoundError:
        return HttpResponse("This version's file is missing.", status=410)
    response = FileResponse(
        handle,
        content_type="application/vnd.oasis.opendocument.text",
        as_attachment=True,
        filename=f"{stem} ({label} v{version.seq}).odt",
    )
    response["Cache-Control"] = "private, no-store"
    return response
