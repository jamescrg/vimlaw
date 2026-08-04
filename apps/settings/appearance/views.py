from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


@login_required
def appearance_index(request):
    context = {
        "subapp": "appearance",
    }
    return render(request, "settings/appearance/index.html", context)


@login_required
@require_POST
def set_nav_layout(request):
    """Persist the user's navigation layout (synced across their devices).

    The client applies the layout to <html> immediately; this just stores it,
    so a 204 (no swap) is all that's needed.
    """
    layout = request.POST.get("nav-layout")
    if layout in {"vertical", "horizontal"}:
        request.user.nav_layout = layout
        request.user.save(update_fields=["nav_layout"])
    return HttpResponse(status=204)
