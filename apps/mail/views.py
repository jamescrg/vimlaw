from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import apps.mail.google as mail_google
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.matters.models import Matter

from .filters import EmailFilter
from .models import Email


def get_emails_data(request, matter, matter_id):
    """Synced emails with session-persisted filters applied, newest first."""
    filter_session_key = get_session_key("emails_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    queryset = Email.objects.filter(matter=matter).order_by("-date")
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

    return {
        "emails": emails,
        "email_count": emails.count(),
        "current_order": current_order,
        "keyword": keyword,
        "filters_active": bool(
            {k: v for k, v in filter_data.items() if k != "order_by" and v}
        ),
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
@require_POST
def email_importance(request, email_id, value):
    """Set an email's importance and re-render the list (mirrors notes)."""
    email = get_object_or_404(Email, pk=email_id)
    if 1 <= value <= 7:
        email.importance = value
        email.save(update_fields=["importance"])
    return emails_list(request, email.matter_id)


# ---------------------------------------------------------------------------
# Gmail label linking (mirrors the Notes tab's Drive folder linking)
# ---------------------------------------------------------------------------


@login_required
def label_link_modal(request, matter_id):
    """Modal to pick this matter's Gmail label from a live list."""
    matter, _ = get_matter_from_url(request, matter_id)

    labels = mail_google.list_matter_labels()
    # Labels already linked to a different matter (prevent mis-linking).
    taken = {
        m.gmail_label_id: m
        for m in Matter.objects.exclude(pk=matter.pk)
        .exclude(gmail_label_id__isnull=True)
        .exclude(gmail_label_id="")
    }
    label_rows = [{**label, "taken_by": taken.get(label["id"])} for label in labels]

    context = {
        "matter": matter,
        "labels": label_rows,
        "current": matter.gmail_label_id,
        "linked": mail_google.check_credentials(),
        "label_root": settings.GMAIL_LABEL_ROOT,
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
