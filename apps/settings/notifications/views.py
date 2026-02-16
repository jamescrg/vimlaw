from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.agenda.tasks_digest import send_digest_for_user


@login_required
def notifications_index(request):
    context = {
        "app": "settings",
        "subapp": "notifications",
    }
    return render(request, "settings/notifications/index.html", context)


@login_required
def toggle_digest(request):
    user = request.user
    user.digest_enabled = not user.digest_enabled
    user.save(update_fields=["digest_enabled"])
    return render(request, "settings/notifications/preferences.html")


@login_required
def toggle_weekends(request):
    user = request.user
    user.digest_include_weekends = not user.digest_include_weekends
    user.save(update_fields=["digest_include_weekends"])
    return render(request, "settings/notifications/preferences.html")


@login_required
def send_test_digest(request):
    user = request.user
    if not user.email:
        return render(
            request,
            "settings/notifications/preferences.html",
            {"test_result": "error", "test_message": "No email address on file."},
        )

    sent = send_digest_for_user(user)
    if sent:
        message = f"Test digest sent to {user.email}."
    else:
        message = "No events or tasks to include — no email sent."

    return render(
        request,
        "settings/notifications/preferences.html",
        {"test_result": "success" if sent else "info", "test_message": message},
    )
