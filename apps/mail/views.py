from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import apps.mail.google as mail_google
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.matters.models import Matter

from .filters import EmailFilter
from .models import Email, GmailAccount


def get_emails_data(request, matter, matter_id):
    """Synced emails with session-persisted filters applied, newest first."""
    filter_session_key = get_session_key("emails_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    # dedup: the same message synced from two mailboxes shows once
    # (first-synced row wins; provenance rows stay in the DB).
    queryset = (
        Email.objects.filter(matter=matter)
        .dedup()
        .order_by("-date")
        .select_related("account")
        .prefetch_related("attachment_files")
    )
    if filter_data:
        emails = EmailFilter(filter_data, queryset=queryset).qs
    else:
        emails = queryset

    current_order = filter_data.get("order_by", "-date")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-date"

    keyword = filter_data.get("keyword", "")
    if isinstance(keyword, list):
        keyword = keyword[0] if keyword else ""

    # DB-only check (no Gmail round-trip): the scheduled sync refreshes each
    # account's missing_labels every tick, so "your mailbox has no label for
    # this matter" is at most a couple of minutes stale.
    own_account = GmailAccount.objects.filter(user=request.user).first()
    own_missing_label = bool(
        own_account
        and matter.gmail_label_name
        and matter.gmail_label_name in (own_account.missing_labels or [])
    )

    return {
        "emails": emails,
        "email_count": emails.count(),
        "current_order": current_order,
        "keyword": keyword,
        "filters_active": bool(
            {k: v for k, v in filter_data.items() if k != "order_by" and v}
        ),
        "gmail_linked": mail_google.check_credentials(),
        "own_missing_label": own_missing_label,
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


@login_required
def emails_filter(request, matter_id):
    """Filter modal for emails (mirrors the notes filter modal)."""
    matter, matters = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("emails_filter", matter_id)

    if request.method == "POST":
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session[filter_session_key] = filter_data
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": "emailsChanged"})

    filter_data = request.session.get(filter_session_key, {})
    filter_obj = EmailFilter(filter_data, queryset=Email.objects.filter(matter=matter))

    return render(
        request, "case/emails/filter.html", {"filter": filter_obj, "matter": matter}
    )


@login_required
def emails_filter_keyword(request, matter_id):
    """Filter emails by subject keyword (toolbar live search)."""
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("emails_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session[filter_session_key] = filter_data

    context = {"matter": matter} | get_emails_data(request, matter, matter_id)
    return render(request, "case/emails/table.html", context)


@login_required
def emails_sort(request, matter_id, order):
    """Sort emails by field, toggling direction on repeat clicks."""
    filter_session_key = get_session_key("emails_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else ""
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:emails-list", matter_id=matter_id)


@login_required
def email_preview(request, email_id):
    """Preview-pane partial for one email."""
    email = get_object_or_404(Email, pk=email_id)
    return render(request, "case/emails/preview.html", {"email": email})


@login_required
@require_POST
def email_promote(request, email_id):
    """Promote an email to a Correspondence Document (PDF in the record)."""
    from .promote import promote_email

    email = get_object_or_404(Email, pk=email_id)
    base_url = request.build_absolute_uri("/").rstrip("/")
    try:
        promote_email(email, request.user, base_url)
    except Exception:
        return HttpResponse(
            '<p class="error-text">Failed to render the email to PDF. '
            "Try again, or check the logs.</p>"
        )
    email.refresh_from_db()
    return render(request, "case/emails/preview.html", {"email": email})


@login_required
@require_POST
def email_importance(request, email_id, value):
    """Set an email's importance and re-render its preview pane."""
    email = get_object_or_404(Email, pk=email_id)
    if 1 <= value <= 7:
        email.importance = value
        email.save(update_fields=["importance"])
    return render(request, "case/emails/preview.html", {"email": email})


# ---------------------------------------------------------------------------
# Gmail label linking (mirrors the Notes tab's Drive folder linking)
# ---------------------------------------------------------------------------


@login_required
def label_link_modal(request, matter_id):
    """Modal to pick this matter's Gmail label from a live list.

    Labels are read from the requester's own mailbox when connected (any
    mailbox otherwise); what gets stored is the label NAME — the
    cross-mailbox contract every account resolves for itself.
    """
    matter, _ = get_matter_from_url(request, matter_id)

    labels = mail_google.list_matter_labels(mail_google.account_for(request.user))
    # Labels already linked to a different matter (prevent mis-linking).
    taken = {
        m.gmail_label_name: m
        for m in Matter.objects.exclude(pk=matter.pk)
        .exclude(gmail_label_name__isnull=True)
        .exclude(gmail_label_name="")
    }
    label_rows = [{**label, "taken_by": taken.get(label["name"])} for label in labels]

    # "Create a label named after the matter" shortcut: the sync provisions
    # the label in every mailbox, so nobody has to touch Gmail first. Only
    # offered while the name is unused and unlinked.
    suggested = mail_google.default_label_name(matter)
    if suggested in taken or any(label["name"] == suggested for label in labels):
        suggested = None
    prefix = f"{settings.GMAIL_LABEL_ROOT}/" if settings.GMAIL_LABEL_ROOT else ""
    suggested_short = suggested.removeprefix(prefix) if suggested else None

    context = {
        "matter": matter,
        "labels": label_rows,
        "current": matter.gmail_label_name,
        "linked": mail_google.check_credentials(),
        "label_root": settings.GMAIL_LABEL_ROOT,
        "suggested_label": suggested,
        "suggested_short": suggested_short,
    }
    return render(request, "case/emails/label-link-modal.html", context)


def _queue_resync(matter):
    """Resync via django-q so linking a large label doesn't block the request.

    Returns the queued task id, or None when the fallback ran inline."""
    try:
        from django_q.tasks import async_task

        return async_task("apps.mail.google.resync_matter_by_id", matter.id)
    except Exception:
        mail_google.resync_matter(matter)
        return None


@login_required
@require_POST
def emails_refresh(request, matter_id):
    """On-demand resync of this matter, ahead of the scheduled sync.

    Queues the same per-matter resync the label views use and swaps the
    Refresh button for a pill that polls emails_refresh_status until the
    task lands."""
    matter, _ = get_matter_from_url(request, matter_id)
    if not (matter.gmail_label_name and mail_google.check_credentials()):
        return HttpResponse(status=204, headers={"HX-Trigger": "emailsChanged"})
    task_id = _queue_resync(matter)
    if task_id is None:
        # Ran inline — the list is already fresh.
        return HttpResponse(status=204, headers={"HX-Trigger": "emailsChanged"})
    return render(
        request,
        "case/emails/refresh-button.html",
        {"matter": matter, "task_id": task_id, "polls": 0},
    )


@login_required
def emails_refresh_status(request, matter_id):
    """Poll target for the refresh pill.

    django-q saves the task row when the resync finishes, so a fetch() hit
    means done: swap the idle button back and reload the list. A poll cap
    backstops a stuck queue — give the button back and refresh anyway."""
    matter, _ = get_matter_from_url(request, matter_id)
    task_id = request.GET.get("task", "")
    try:
        polls = int(request.GET.get("polls", 0))
    except ValueError:
        polls = 0

    finished = not task_id
    if task_id:
        try:
            from django_q.tasks import fetch

            finished = fetch(task_id) is not None
        except Exception:
            finished = True

    if finished or polls >= 60:
        response = render(
            request, "case/emails/refresh-button.html", {"matter": matter}
        )
        response["HX-Trigger"] = "emailsChanged"
        return response

    return render(
        request,
        "case/emails/refresh-button.html",
        {"matter": matter, "task_id": task_id, "polls": polls + 1},
    )


@login_required
@require_POST
def label_link(request, matter_id):
    """Set this matter's Gmail label and resync its emails."""
    matter, _ = get_matter_from_url(request, matter_id)
    # create_label_name is the "create a label named after the matter"
    # shortcut; the sync provisions it in every mailbox on resync.
    label_name = (
        request.POST.get("create_label_name") or request.POST.get("label_name") or ""
    ).strip()

    if label_name:
        clash = (
            Matter.objects.exclude(pk=matter.pk)
            .filter(gmail_label_name=label_name)
            .first()
        )
        if clash:
            # 200 so HTMX swaps the message into the modal's error slot.
            return HttpResponse(
                f'<p class="error-text">“{label_name}” is already '
                f"linked to {clash}. Unlink it there first.</p>"
            )

    matter.gmail_label_name = label_name or None
    matter.gmail_label_id = None  # legacy per-mailbox id, no longer stored
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
