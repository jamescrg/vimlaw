"""Calendar sync orchestration.

Keeps the inline push-on-save (immediacy + the failure toast) working, while
making the whole thing eventually-consistent: `reconcile()` re-pushes anything
that still needs it. "Needs pushing" is derived purely from the data —
google_synced_at IS NULL (never pushed) or updated_at > google_synced_at (edited
since the last push) — so a failed push needs no special flag: it just leaves
google_synced_at behind and the next reconcile retries it. This one comparison
also covers the first-ever connect (every Pending event has a NULL
google_synced_at, so reconnecting adopts them all).
"""

from logging import getLogger

from django.db.models import F, Q

import apps.calendar.google as google
from apps.calendar.models import Event, PendingGoogleDeletion

logger = getLogger(__name__)

# Only Pending events are mirrored to Google — matching the app's own calendar
# scope. Completed/Missed events stop syncing; they remain on Google as last
# pushed (we don't unsync them).
SYNC_STATUS = "Pending"


def push_event(event):
    """Push one event to Google. Returns 'ok' | 'failed' | 'skipped'.

    'skipped' = not connected, or out of scope (not Pending).
    'failed'  = sync attempted but the API call failed; google_synced_at is left
                behind so reconcile() retries it.
    """
    if not google.check_credentials():
        return "skipped"
    if event.status != SYNC_STATUS:
        return "skipped"

    if event.google_id:
        ok = bool(google.edit_event(event))
    else:
        google_id = google.add_event(event)
        ok = bool(google_id)
        if ok:
            event.google_id = google_id

    if not ok:
        return "failed"

    # Mark synced. .update() (not .save()) so we don't re-bump updated_at or add
    # a stray history row; F("updated_at") pins synced_at to the row's current
    # edit time, so it's only "dirty" again after a genuine later edit.
    Event.objects.filter(pk=event.pk).update(
        google_id=event.google_id,
        google_synced_at=F("updated_at"),
    )
    return "ok"


def delete_event_remote(event):
    """Remove an event from Google after a local delete. Returns
    'ok' | 'failed' | 'queued' | 'skipped'. Queues a retry on failure or when
    offline so reconcile() can finish it once connected. Not scope-gated —
    anything with a google_id must be removed to avoid orphans."""
    if not event.google_id:
        return "skipped"

    if not google.check_credentials():
        _queue_deletion(event.google_id)
        return "queued"

    if google.delete_event(event):
        return "ok"

    _queue_deletion(event.google_id)
    return "failed"


def _queue_deletion(google_id):
    PendingGoogleDeletion.objects.get_or_create(
        google_id=google_id,
        defaults={"calendar_id": google.CALENDAR_ID or ""},
    )


def reconcile():
    """Flush pending local changes to Google and drain queued deletions.

    Idempotent and safe to run repeatedly — called on (re)connect and from the
    sync_calendar cron (before the pull). No-op when not connected.
    """
    summary = {"pushed": 0, "deleted": 0, "failed": 0}
    if not google.check_credentials():
        return summary

    # Deletions first, so local removals reach Google before the pull (which
    # would otherwise re-create them) and a re-created-then-deleted id can't
    # linger.
    for pending in PendingGoogleDeletion.objects.all():
        if google.delete_event_by_id(pending.google_id):
            pending.delete()
            summary["deleted"] += 1
        else:
            summary["failed"] += 1

    # Pending events never pushed, or edited since their last successful push.
    needs_push = Event.objects.filter(status=SYNC_STATUS).filter(
        Q(google_synced_at__isnull=True) | Q(updated_at__gt=F("google_synced_at"))
    )
    for event in needs_push.iterator():
        result = push_event(event)
        if result == "ok":
            summary["pushed"] += 1
        elif result == "failed":
            summary["failed"] += 1

    logger.info(
        "Calendar reconcile: pushed=%(pushed)s deleted=%(deleted)s failed=%(failed)s",
        summary,
    )
    return summary


def scheduled_sync():
    reconciled = reconcile()
    pulled = google.sync_from_google()

    return {"reconciled": reconciled, "pulled": pulled}
