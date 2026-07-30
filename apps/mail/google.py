"""Gmail case-email sync.

Pulls labeled Gmail messages into the database as ``Email`` rows. Each matter
maps to one Gmail label (``Matter.gmail_label_id``, set via the Emails-tab
link modal or the link_gmail_labels command); applying that label to a message
in Gmail brings it onto the matter, removing the label (or trashing the
message) takes it off. Reuses the project's Google OAuth plumbing (see
apps/calendar/google.py) and the Gmail History API for incremental sync.

Storage model (DB-canonical, text only):
- Parsed body text lives in ``Email.body_text`` (Postgres) — Gmail remains the
  archive of record and ``Email.gmail_url`` deep-links back to the original.
  Attachments are recorded as metadata only, never fetched.

Flow:
- bootstrap(): first run (no saved history id) lists every message under each
  mapped label, stores the new ones, reconciles removals, and records the
  mailbox ``historyId`` (captured *before* listing, so nothing falls in the
  gap) as the incremental cursor.
- sync(): on each tick, consume ``users.history.list`` since the saved cursor:
  mapped label added → fetch + store; mapped label removed / message trashed
  or deleted → drop the row(s). A stale cursor (HTTP 404) clears the state
  and re-bootstraps, mirroring the Drive sync's 410 handling.
"""

import json
import logging

import google.oauth2.credentials
from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from apps.matters.models import Matter
from utils.prepare_path import prepare_path

from . import parser
from .models import Email, GmailSyncState

logger = logging.getLogger(__name__)

GMAIL_TOKEN_PATH = "google/email_tokens.json"

# Applying TRASH is how deletion first appears in the history feed (permanent
# removal arrives later as messagesDeleted).
TRASH_LABEL = "TRASH"


# --------------------------------------------------------------------------- #
# Auth (mirrors apps/drive/google.py)
# --------------------------------------------------------------------------- #
def check_credentials():
    """Return True if a Gmail account is linked (token file holds a token)."""
    prepare_path(GMAIL_TOKEN_PATH)
    try:
        with open(GMAIL_TOKEN_PATH, "r") as f:
            credentials = f.read()
    except FileNotFoundError:
        return False
    return "token" in credentials


def build_service():
    """Build an authenticated Gmail v1 service, or False if not linked."""
    prepare_path(GMAIL_TOKEN_PATH)

    with open(GMAIL_TOKEN_PATH, "r") as f:
        token = f.read()

    if not token:
        return False

    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
        json.loads(token)
    )
    return build("gmail", "v1", credentials=credentials)


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #
def list_labels(service=None):
    """Return [{"id", "name"}] for the mailbox's user-created labels.

    Fails soft (returns []) if Gmail is unlinked or the API errors, so the
    label-picker modal degrades to an empty list instead of a 500.
    """
    if service is None:
        if not check_credentials():
            return []
        service = build_service()
    try:
        resp = service.users().labels().list(userId="me").execute()
    except HttpError:
        logger.exception("Failed to list Gmail labels")
        return []
    return sorted(
        (
            {"id": label["id"], "name": label["name"]}
            for label in resp.get("labels", [])
            if label.get("type") == "user"
        ),
        key=lambda label: label["name"].lower(),
    )


def list_matter_labels(service=None):
    """User labels offered in the matter-link picker.

    Scoped to children of settings.GMAIL_LABEL_ROOT (the label hierarchy's
    "Matters - Open" analog of DRIVE_NOTES_ROOT), each carrying a
    ``short_name`` with the root prefix stripped for display. A blank root
    offers every user label.
    """
    labels = list_labels(service)
    root = settings.GMAIL_LABEL_ROOT
    if not root:
        return [{**label, "short_name": label["name"]} for label in labels]
    prefix = root + "/"
    return [
        {**label, "short_name": label["name"][len(prefix) :]}
        for label in labels
        if label["name"].startswith(prefix)
    ]


def _mapped_matters():
    """Return {gmail_label_id: Matter} for all label-linked matters."""
    return {
        m.gmail_label_id: m
        for m in Matter.objects.exclude(gmail_label_id__isnull=True).exclude(
            gmail_label_id=""
        )
    }


def _refresh_label_names(service, mapped, state, dry_run):
    """Refresh Matter.gmail_label_name snapshots; record deleted labels."""
    labels = {label["id"]: label["name"] for label in list_labels(service)}
    missing = []
    for label_id, matter in mapped.items():
        name = labels.get(label_id)
        if name is None:
            missing.append(label_id)
        elif name != matter.gmail_label_name and not dry_run:
            # Queryset update: a name snapshot refresh shouldn't spam the
            # matter's simple-history.
            Matter.objects.filter(pk=matter.pk).update(gmail_label_name=name)
    state.missing_labels = sorted(missing)
    return missing


# --------------------------------------------------------------------------- #
# Message ingestion
# --------------------------------------------------------------------------- #
def _new_stats():
    return {"created": 0, "skipped": 0, "removed": 0, "failed": 0}


def _fetch_and_store(service, matter, label_id, gmail_id, stats, dry_run):
    """Fetch one message and store it on the matter (skip if already synced)."""
    if Email.objects.filter(matter=matter, gmail_id=gmail_id).exists():
        stats["skipped"] += 1
        return
    if dry_run:
        stats["created"] += 1
        return
    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=gmail_id, format="full")
            .execute()
        )
        parsed = parser.parse_payload(msg)
        Email.objects.create(
            matter=matter,
            gmail_id=gmail_id,
            thread_id=msg.get("threadId", ""),
            label_id=label_id,
            sender=parsed.sender,
            recipients=parsed.recipients,
            subject=parsed.subject,
            date=parsed.date,
            snippet=parsed.snippet,
            body_text=parsed.body_text,
            body_html=parsed.body_html,
            body_source=parsed.body_source,
            attachments=parsed.attachments,
        )
        stats["created"] += 1
    except HttpError as e:
        # A message can vanish between the listing and the fetch.
        if e.resp.status == 404:
            stats["skipped"] += 1
            return
        raise
    except Exception:
        stats["failed"] += 1
        logger.exception(
            "Failed to sync Gmail message %s for matter %s", gmail_id, matter.pk
        )


def _list_label_message_ids(service, label_id):
    """Yield every message id currently under a label (paged)."""
    page_token = None
    while True:
        kwargs = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        for ref in resp.get("messages", []):
            yield ref["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


def _remove_email(matter, gmail_id, stats, dry_run):
    if dry_run:
        stats["removed"] += Email.objects.filter(
            matter=matter, gmail_id=gmail_id
        ).count()
        return
    deleted, _ = Email.objects.filter(matter=matter, gmail_id=gmail_id).delete()
    stats["removed"] += deleted


def _remove_everywhere(gmail_id, stats, dry_run):
    if dry_run:
        stats["removed"] += Email.objects.filter(gmail_id=gmail_id).count()
        return
    deleted, _ = Email.objects.filter(gmail_id=gmail_id).delete()
    stats["removed"] += deleted


# --------------------------------------------------------------------------- #
# Bootstrap + incremental sync
# --------------------------------------------------------------------------- #
def _bootstrap(service, state, mapped, dry_run):
    """Full sync: list every mapped label, reconcile, set the history cursor."""
    stats = _new_stats()

    # Capture the cursor BEFORE listing so anything that arrives mid-crawl is
    # replayed by the first incremental tick instead of falling in the gap.
    profile = service.users().getProfile(userId="me").execute()
    start_history_id = str(profile.get("historyId", ""))

    _refresh_label_names(service, mapped, state, dry_run)
    missing = set(state.missing_labels)

    for label_id, matter in mapped.items():
        if label_id in missing:
            continue
        seen = set()
        for gmail_id in _list_label_message_ids(service, label_id):
            seen.add(gmail_id)
            _fetch_and_store(service, matter, label_id, gmail_id, stats, dry_run)
        # Reconcile: drop rows un-labeled/deleted while sync was down.
        stale = Email.objects.filter(matter=matter).exclude(gmail_id__in=seen)
        if dry_run:
            stats["removed"] += stale.count()
        else:
            deleted, _ = stale.delete()
            stats["removed"] += deleted

    if not dry_run:
        state.history_id = start_history_id
        state.save()

    logger.info(
        "Gmail bootstrap complete: %s (missing labels: %s)", stats, sorted(missing)
    )
    return {**stats, "missing_labels": sorted(missing)}


def _process_history_record(service, record, mapped, stats, dry_run):
    for added in record.get("messagesAdded", []):
        message = added.get("message", {})
        for label_id in message.get("labelIds", []):
            if label_id in mapped:
                _fetch_and_store(
                    service, mapped[label_id], label_id, message["id"], stats, dry_run
                )

    for added in record.get("labelsAdded", []):
        message = added.get("message", {})
        label_ids = added.get("labelIds", [])
        if TRASH_LABEL in label_ids:
            _remove_everywhere(message["id"], stats, dry_run)
            continue
        for label_id in label_ids:
            if label_id in mapped:
                _fetch_and_store(
                    service, mapped[label_id], label_id, message["id"], stats, dry_run
                )

    for removed in record.get("labelsRemoved", []):
        message = removed.get("message", {})
        for label_id in removed.get("labelIds", []):
            if label_id in mapped:
                _remove_email(mapped[label_id], message["id"], stats, dry_run)

    for deleted in record.get("messagesDeleted", []):
        message = deleted.get("message", {})
        _remove_everywhere(message["id"], stats, dry_run)


def _is_rate_limit(e):
    if e.resp.status == 429:
        return True
    if e.resp.status == 403:
        try:
            reason = e.error_details[0].get("reason", "")
        except (AttributeError, IndexError, TypeError):
            reason = ""
        return "rate" in str(reason).lower() or "rateLimit" in str(e)
    return False


def sync(dry_run=False, full=False):
    """Run one sync tick. Returns a stats dict, or None when not linked.

    ``full`` (or a missing cursor) triggers a bootstrap; otherwise the history
    delta since the saved cursor is consumed.
    """
    if not check_credentials():
        return None
    mapped = _mapped_matters()
    if not mapped:
        return None

    service = build_service()
    state, _ = GmailSyncState.objects.get_or_create(pk=1)

    if full or not state.history_id:
        return _bootstrap(service, state, mapped, dry_run)

    stats = _new_stats()
    _refresh_label_names(service, mapped, state, dry_run)
    page_token = None
    new_history_id = None
    try:
        while True:
            kwargs = {
                "userId": "me",
                "startHistoryId": state.history_id,
                "maxResults": 500,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.users().history().list(**kwargs).execute()

            for record in resp.get("history", []):
                _process_history_record(service, record, mapped, stats, dry_run)

            new_history_id = resp.get("historyId", new_history_id)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        if not dry_run:
            if new_history_id:
                state.history_id = str(new_history_id)
            state.save()
    except HttpError as e:
        # 404 => the start history id has expired; clear it and re-bootstrap.
        if e.resp.status == 404:
            logger.warning("Gmail history id expired; re-bootstrapping.")
            state.history_id = None
            if not dry_run:
                state.save()
            return sync(dry_run=dry_run, full=True)
        if _is_rate_limit(e):
            # Bail on this tick; the saved cursor makes the next tick resume.
            logger.warning("Gmail rate limit hit; deferring to next tick.")
            return {**stats, "missing_labels": state.missing_labels}
        raise

    logger.info("Gmail sync complete: %s", stats)
    return {**stats, "missing_labels": state.missing_labels}


# --------------------------------------------------------------------------- #
# Per-matter resync (used by the Emails-tab "Link Gmail Label" UI)
# --------------------------------------------------------------------------- #
def resync_matter(matter):
    """Re-sync just one matter's emails from its linked label.

    Used when a user links/changes/unlinks a matter's Gmail label: ingests the
    label's messages and removes rows no longer under it. If the matter is
    unlinked, simply drops its synced emails. No-op when Gmail is not linked.
    Returns a stats dict.
    """
    if not check_credentials():
        return None

    stats = _new_stats()

    if not matter.gmail_label_id:
        deleted, _ = Email.objects.filter(matter=matter).delete()
        stats["removed"] += deleted
        return stats

    service = build_service()
    seen = set()
    try:
        for gmail_id in _list_label_message_ids(service, matter.gmail_label_id):
            seen.add(gmail_id)
            _fetch_and_store(
                service, matter, matter.gmail_label_id, gmail_id, stats, False
            )
    except HttpError as e:
        # Label deleted in Gmail => list fails; keep existing rows and let the
        # main sync surface it via missing_labels.
        if e.resp.status in (400, 404):
            logger.warning(
                "Gmail label %s for matter %s not listable",
                matter.gmail_label_id,
                matter.pk,
            )
            return stats
        raise

    deleted, _ = Email.objects.filter(matter=matter).exclude(gmail_id__in=seen).delete()
    stats["removed"] += deleted
    return stats


def resync_matter_by_id(matter_id):
    """async_task entry point for the link/unlink views."""
    matter = Matter.objects.filter(pk=matter_id).first()
    if matter is None:
        return None
    return resync_matter(matter)


# --------------------------------------------------------------------------- #
# Status + scheduling entry points
# --------------------------------------------------------------------------- #
def get_sync_status():
    """Summary for the Settings > Integrations health panel (DB-only)."""
    state = GmailSyncState.objects.first()
    linked_matters = (
        Matter.objects.exclude(gmail_label_id__isnull=True)
        .exclude(gmail_label_id="")
        .count()
    )
    return {
        "linked": check_credentials(),
        "synced_count": Email.objects.count(),
        "linked_matters": linked_matters,
        "missing_labels": state.missing_labels if state else [],
        "last_sync_at": state.last_sync_at if state else None,
    }


def scheduled_sync():
    """django-q entry point (gmail-sync schedule)."""
    return sync()


def scheduled_sync_full():
    """django-q entry point (gmail-sync-weekly-full schedule)."""
    return sync(full=True)
