"""Views for linking a draft to a case AI conversation.

The chat window's paperclip button opens the picker (the matter's Drive ODT
files); choosing one creates the DraftLink and the chip partial swaps in.
The companion setup modal (extension download) is reachable from the picker.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from apps.case.ai.models import Conversation
from apps.drafts import services
from apps.drafts.models import CompanionToken
from apps.drive import google

logger = logging.getLogger(__name__)


def _get_conversation(conv_id):
    return get_object_or_404(Conversation.objects.select_related("matter"), pk=conv_id)


def _chip_response(request, conversation):
    response = render(
        request,
        "case/ai/draft-chip.html",
        {"conversation": conversation, "matter": conversation.matter},
    )
    response["HX-Trigger"] = "draftLinkChanged"
    return response


@login_required
def draft_picker(request, conv_id):
    """Modal listing the matter's Drive ODT files."""
    conversation = _get_conversation(conv_id)
    matter = conversation.matter
    drive_ready = bool(matter and matter.drive_folder) and google.check_credentials()
    return render(
        request,
        "case/ai/draft-picker.html",
        {
            "conversation": conversation,
            "matter": matter,
            "drive_ready": drive_ready,
            "files": services.list_matter_odt_files(matter) if drive_ready else [],
        },
    )


@login_required
@require_http_methods(["POST"])
def draft_link(request, conv_id):
    """Link the conversation to the chosen Drive file."""
    conversation = _get_conversation(conv_id)
    drive_file_id = request.POST.get("file", "")
    if not drive_file_id:
        return HttpResponse("Missing file parameter.", status=400)
    try:
        services.create_link(conversation, drive_file_id)
    except services.DraftError as exc:
        return HttpResponse(str(exc), status=502)
    conversation.refresh_from_db()
    return _chip_response(request, conversation)


@login_required
@require_http_methods(["POST"])
def draft_unlink(request, conv_id):
    """Remove the conversation's draft link (the document is untouched)."""
    conversation = _get_conversation(conv_id)
    link = getattr(conversation, "draft_link", None)
    if link is not None:
        link.delete()
        conversation.refresh_from_db()
    return _chip_response(request, conversation)


@login_required
def draft_chip(request, conv_id):
    """The chip partial, fetched once a new conversation's row exists."""
    conversation = _get_conversation(conv_id)
    return render(
        request,
        "case/ai/draft-chip.html",
        {"conversation": conversation, "matter": conversation.matter},
    )


@login_required
def draft_companion_setup(request):
    """Modal with the personalized extension download and install steps."""
    return render(
        request,
        "case/ai/companion-setup.html",
        {"token": CompanionToken.for_user(request.user)},
    )
