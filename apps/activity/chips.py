"""User-chip pinning for the Activity toolbars.

The chip row itself is the shared components/user-chips.html include; the
pinned set lives on CustomUser.task_user_chips and is shared with the
tasks tab (one working set of people per viewer). This endpoint serves all
three Activity tabs: only the mounted tab's container listens for its
refresh event, so firing every tab's trigger refreshes whichever list is
on screen.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.accounts.models import CustomUser
from apps.tasks.tasks import TASK_CHIPS_CAP, toggle_chip_pin
from utils.toasts import toast_warning

ACTIVITY_TRIGGERS = "timeChanged, expensesChanged, flatFeesChanged"


@login_required
@require_POST
def activity_toggle_chip(request, user_id):
    """Pin or unpin a user on the Activity toolbars' chip row."""
    get_object_or_404(CustomUser, pk=user_id, is_active=True)
    pinned = toggle_chip_pin(request.user, user_id)
    response = HttpResponse(status=204, headers={"HX-Trigger": ACTIVITY_TRIGGERS})
    if not pinned:
        toast_warning(
            response,
            f"Chips are limited to {TASK_CHIPS_CAP}. Unpin one first.",
        )
    return response
