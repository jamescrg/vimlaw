from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

import apps.mail.google as mail_google
from apps.case.views import get_matter_from_url, set_last_tab
from apps.matters.models import Matter

from .ai import group_by_thread
from .models import Email


def get_emails_data(request, matter, matter_id):
    """Emails grouped by Gmail thread, newest thread first."""
    emails = Email.objects.filter(matter=matter)
    thread_list = sorted(
        group_by_thread(emails),
        key=lambda msgs: msgs[-1].date or msgs[-1].created_at,
        reverse=True,
    )
    return {
        "email_threads": thread_list,
        "email_count": emails.count(),
        "gmail_linked": mail_google.check_credentials(),
    }


@login_required
def emails_index(request, matter_id):
    """Main emails view (the case Emails tab)."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "emails")

    context = {
        "app": "matters",
        "subapp": "emails",
        "matter": matter,
        "matters": matters,
    } | get_emails_data(request, matter, matter_id)

    return render(request, "case/emails/main.html", context)


@login_required
def emails_list(request, matter_id):
    """List partial for HTMX refreshes."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "matter": matter,
        "matters": matters,
    } | get_emails_data(request, matter, matter_id)

    return render(request, "case/emails/list.html", context)


# ---------------------------------------------------------------------------
# Gmail label linking (mirrors the Notes tab's Drive folder linking)
# ---------------------------------------------------------------------------


@login_required
def label_link_modal(request, matter_id):
    """Modal to pick this matter's Gmail label from a live list."""
    matter, _ = get_matter_from_url(request, matter_id)

    labels = mail_google.list_labels()
    # Labels already linked to a different matter (prevent mis-linking).
    taken = {
        m.gmail_label_id: m
        for m in Matter.objects.exclude(pk=matter.pk)
        .exclude(gmail_label_id__isnull=True)
        .exclude(gmail_label_id="")
    }
    label_rows = [
        {"id": label["id"], "name": label["name"], "taken_by": taken.get(label["id"])}
        for label in labels
    ]

    context = {
        "matter": matter,
        "labels": label_rows,
        "current": matter.gmail_label_id,
        "linked": mail_google.check_credentials(),
    }
    return render(request, "case/emails/label-link-modal.html", context)


def _queue_resync(matter):
    """Resync via django-q so linking a large label doesn't block the request."""
    try:
        from django_q.tasks import async_task

        async_task("apps.mail.google.resync_matter_by_id", matter.id)
    except Exception:
        mail_google.resync_matter(matter)


@login_required
@require_POST
def label_link(request, matter_id):
    """Set this matter's Gmail label and resync its emails."""
    matter, _ = get_matter_from_url(request, matter_id)
    label_id = request.POST.get("label", "").strip()
    label_name = request.POST.get("label_name", "").strip()

    if label_id:
        clash = (
            Matter.objects.exclude(pk=matter.pk).filter(gmail_label_id=label_id).first()
        )
        if clash:
            # 200 so HTMX swaps the message into the modal's error slot.
            return HttpResponse(
                f'<p class="error-text">“{label_name or label_id}” is already '
                f"linked to {clash}. Unlink it there first.</p>"
            )

    matter.gmail_label_id = label_id or None
    matter.gmail_label_name = label_name or None
    matter.save(update_fields=["gmail_label_id", "gmail_label_name"])
    _queue_resync(matter)

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


@login_required
@require_POST
def label_unlink(request, matter_id):
    """Unlink this matter's Gmail label and remove its synced emails."""
    matter, _ = get_matter_from_url(request, matter_id)
    matter.gmail_label_id = None
    matter.gmail_label_name = None
    matter.save(update_fields=["gmail_label_id", "gmail_label_name"])
    _queue_resync(matter)

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})
