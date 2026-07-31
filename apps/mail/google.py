"""Gmail case-email sync (multi-account).

Pulls labeled Gmail messages into the database as ``Email`` rows, from every
connected mailbox (``GmailAccount``, one per user). Each matter maps to one
Gmail label NAME (``Matter.gmail_label_name``, set via the Emails-tab link
modal or the link_gmail_labels command) — the name is the cross-mailbox
contract: every account resolves it to its own label id at sync time, so
staff just create the same labels under GMAIL_LABEL_ROOT in each mailbox.
Applying the label to a message brings it onto the matter; removing the label
(or trashing the message) takes that mailbox's copy off. The same message
labeled in two mailboxes yields one row per account (provenance); display
and AI collapse them by RFC-822 Message-ID (``EmailQuerySet.dedup``).
Reuses the project's Google OAuth plumbing (see apps/calendar/google.py) and
the Gmail History API for incremental sync (one cursor per account).

Storage model (DB-canonical, text only):
- Parsed body text lives in ``Email.body_text`` (Postgres) — Gmail remains the
  archive of record and ``Email.gmail_url`` deep-links back to the original.
  Attachments are recorded as metadata only, never fetched.

Flow:
- bootstrap(): first run for an account (no saved history id) lists every
  message under each resolved label, stores the new ones, reconciles
  removals, and records the mailbox ``historyId`` (captured *before*
  listing, so nothing falls in the gap) as that account's cursor.
- sync(): on each tick, for each account, consume ``users.history.list``
  since its cursor: mapped label added → fetch + store; mapped label removed
  / message trashed or deleted → drop that account's row(s). A stale cursor
  (HTTP 404) clears it and re-bootstraps that account, mirroring the Drive
  sync's 410 handling. One account failing never blocks the others.
"""

import json
import logging

import google.oauth2.credentials
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from apps.matters.models import Matter

from . import parser
from .models import Email, EmailAttachment, GmailAccount


def _queue_attachment_extraction(email_id):
    """Extract attachment text in the background (inline if the queue is down)."""
    try:
        from django_q.tasks import async_task

        async_task("apps.mail.tasks.process_email_attachments", email_id)
    except Exception:
        from . import tasks

        tasks.process_email_attachments(email_id)


logger = logging.getLogger(__name__)

# Legacy single-mailbox token file — read only by the adopt_gmail_account
# command, which migrates it into a GmailAccount row.
GMAIL_TOKEN_PATH = "google/email_tokens.json"

# Applying TRASH is how deletion first appears in the history feed (permanent
# removal arrives later as messagesDeleted).
TRASH_LABEL = "TRASH"


# --------------------------------------------------------------------------- #
# Auth (per-account; token JSON lives on GmailAccount)
# --------------------------------------------------------------------------- #
def check_credentials():
    """Return True if at least one Gmail mailbox is connected."""
    return GmailAccount.objects.exists()


def build_service(account):
    """Build an authenticated Gmail v1 service for one account, or False."""
    if account is None or not account.token:
        return False
    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
        json.loads(account.token)
    )
    return build("gmail", "v1", credentials=credentials)


def account_for(user):
    """The user's own connected mailbox, else any mailbox, else None.

    Label pickers only need *some* mailbox to read label names from (the
    name is the contract), but prefer the user's own so a picker never
    stalls on a colleague's expired token.
    """
    own = GmailAccount.objects.filter(user=user).first()
    return own or GmailAccount.objects.order_by("id").first()


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #
def list_labels(service):
    """Return [{"id", "name"}] for the mailbox's user-created labels.

    Fails soft (returns []) if the API errors, so the label-picker modal
    degrades to an empty list instead of a 500.
    """
    if not service:
        return []
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


def list_matter_labels(account):
    """User labels offered in the matter-link picker, read from ``account``.

    Scoped to children of settings.GMAIL_LABEL_ROOT (the label hierarchy's
    "Matters - Open" analog of DRIVE_NOTES_ROOT), each carrying a
    ``short_name`` with the root prefix stripped for display. A blank root
    offers every user label. What the picker stores is the label NAME —
    other mailboxes resolve it to their own label id at sync time.
    """
    labels = list_labels(build_service(account))
    root = settings.GMAIL_LABEL_ROOT
    if not root:
        return [{**label, "short_name": label["name"]} for label in labels]
    prefix = root + "/"
    return [
        {**label, "short_name": label["name"][len(prefix) :]}
        for label in labels
        if label["name"].startswith(prefix)
    ]


def _matters_by_label_name():
    """Return {gmail_label_name: Matter} for all label-linked matters."""
    return {
        m.gmail_label_name: m
        for m in Matter.objects.exclude(gmail_label_name__isnull=True).exclude(
            gmail_label_name=""
        )
    }


def _resolve_labels(service, matters_by_name):
    """Resolve matter label names to this mailbox's own label ids.

    Returns ``(mapped, missing)``: ``{label_id: Matter}`` for names present
    in the mailbox, plus the sorted label names it has no label for (a
    mailbox that hasn't created a matter's label simply doesn't contribute
    to it — surfaced on the integrations page, existing rows kept).
    """
    ids_by_name = {label["name"]: label["id"] for label in list_labels(service)}
    mapped, missing = {}, []
    for name, matter in matters_by_name.items():
        label_id = ids_by_name.get(name)
        if label_id is None:
            missing.append(name)
        else:
            mapped[label_id] = matter
    return mapped, sorted(missing)


def _account_scope(account):
    """Q filter for rows belonging to this mailbox.

    Pre-multi-account rows (NULL account, awaiting adopt_gmail_account) are
    treated as belonging to whichever account touches them: gmail_ids are
    mailbox-local, so only the original mailbox's sync can ever match them.
    """
    return Q(account=account) | Q(account__isnull=True)


# --------------------------------------------------------------------------- #
# Message ingestion
# --------------------------------------------------------------------------- #
def _new_stats():
    return {"created": 0, "skipped": 0, "removed": 0, "failed": 0}


def _fetch_and_store(service, account, matter, label_id, gmail_id, stats, dry_run):
    """Fetch one message and store it on the matter (skip if already synced).

    Scope: this account's rows plus legacy NULL-account rows (gmail_ids are
    mailbox-local, so a NULL row matching this gmail_id can only have come
    from this same mailbox — re-syncing it would duplicate content).
    """
    if (
        Email.objects.filter(matter=matter, gmail_id=gmail_id)
        .filter(_account_scope(account))
        .exists()
    ):
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
        email = Email.objects.create(
            matter=matter,
            account=account,
            gmail_id=gmail_id,
            message_id=parsed.message_id,
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
        )
        if parsed.attachments:
            EmailAttachment.objects.bulk_create(
                EmailAttachment(
                    email=email,
                    gmail_attachment_id=a["attachment_id"],
                    filename=a["filename"][:255],
                    mime_type=a["mime_type"][:100],
                    size=a["size"],
                )
                for a in parsed.attachments
            )
            _queue_attachment_extraction(email.id)
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


def _remove_email(account, matter, gmail_id, stats, dry_run):
    """Unlabeled in this mailbox: drop only this account's row (a colleague's
    copy of the same message keeps the email on the matter)."""
    qs = Email.objects.filter(matter=matter, gmail_id=gmail_id).filter(
        _account_scope(account)
    )
    if dry_run:
        stats["removed"] += qs.count()
        return
    deleted, _ = qs.delete()
    stats["removed"] += deleted


def _remove_everywhere(account, gmail_id, stats, dry_run):
    """Trashed/deleted in this mailbox: drop this account's rows across all
    matters (gmail_ids are mailbox-local, so cross-matter — not
    cross-account — removal is what "everywhere" means)."""
    qs = Email.objects.filter(gmail_id=gmail_id).filter(_account_scope(account))
    if dry_run:
        stats["removed"] += qs.count()
        return
    deleted, _ = qs.delete()
    stats["removed"] += deleted


# --------------------------------------------------------------------------- #
# Bootstrap + incremental sync
# --------------------------------------------------------------------------- #
def _bootstrap(service, account, mapped, dry_run):
    """Full sync of one mailbox: list every resolved label, reconcile this
    account's rows, set its history cursor."""
    stats = _new_stats()

    # Capture the cursor BEFORE listing so anything that arrives mid-crawl is
    # replayed by the first incremental tick instead of falling in the gap.
    profile = service.users().getProfile(userId="me").execute()
    start_history_id = str(profile.get("historyId", ""))

    for label_id, matter in mapped.items():
        seen = set()
        for gmail_id in _list_label_message_ids(service, label_id):
            seen.add(gmail_id)
            _fetch_and_store(
                service, account, matter, label_id, gmail_id, stats, dry_run
            )
        # Reconcile: drop this account's rows un-labeled/deleted while sync
        # was down. Other accounts' rows for the matter are theirs to keep.
        stale = (
            Email.objects.filter(matter=matter)
            .filter(_account_scope(account))
            .exclude(gmail_id__in=seen)
        )
        if dry_run:
            stats["removed"] += stale.count()
        else:
            deleted, _ = stale.delete()
            stats["removed"] += deleted

    if not dry_run:
        account.history_id = start_history_id
        account.save(update_fields=["history_id"])

    logger.info("Gmail bootstrap complete for %s: %s", account, stats)
    return stats


def _process_history_record(service, account, record, mapped, stats, dry_run):
    for added in record.get("messagesAdded", []):
        message = added.get("message", {})
        for label_id in message.get("labelIds", []):
            if label_id in mapped:
                _fetch_and_store(
                    service,
                    account,
                    mapped[label_id],
                    label_id,
                    message["id"],
                    stats,
                    dry_run,
                )

    for added in record.get("labelsAdded", []):
        message = added.get("message", {})
        label_ids = added.get("labelIds", [])
        if TRASH_LABEL in label_ids:
            _remove_everywhere(account, message["id"], stats, dry_run)
            continue
        for label_id in label_ids:
            if label_id in mapped:
                _fetch_and_store(
                    service,
                    account,
                    mapped[label_id],
                    label_id,
                    message["id"],
                    stats,
                    dry_run,
                )

    for removed in record.get("labelsRemoved", []):
        message = removed.get("message", {})
        for label_id in removed.get("labelIds", []):
            if label_id in mapped:
                _remove_email(account, mapped[label_id], message["id"], stats, dry_run)

    for deleted in record.get("messagesDeleted", []):
        message = deleted.get("message", {})
        _remove_everywhere(account, message["id"], stats, dry_run)


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


def _sync_account(account, matters_by_name, dry_run=False, full=False):
    """Run one sync tick for one mailbox. Returns a stats dict, or None when
    the account's service can't be built.

    ``full`` (or a missing cursor) triggers a bootstrap; otherwise the history
    delta since the account's saved cursor is consumed.
    """
    service = build_service(account)
    if not service:
        return None

    mapped, missing = _resolve_labels(service, matters_by_name)
    if not dry_run and missing != account.missing_labels:
        account.missing_labels = missing
        account.save(update_fields=["missing_labels"])

    if full or not account.history_id:
        return _bootstrap(service, account, mapped, dry_run)

    stats = _new_stats()
    page_token = None
    new_history_id = None
    try:
        while True:
            kwargs = {
                "userId": "me",
                "startHistoryId": account.history_id,
                "maxResults": 500,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.users().history().list(**kwargs).execute()

            for record in resp.get("history", []):
                _process_history_record(
                    service, account, record, mapped, stats, dry_run
                )

            new_history_id = resp.get("historyId", new_history_id)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        if not dry_run and new_history_id:
            account.history_id = str(new_history_id)
            account.save(update_fields=["history_id"])
    except HttpError as e:
        # 404 => the start history id has expired; clear it and re-bootstrap.
        if e.resp.status == 404:
            logger.warning(
                "Gmail history id expired for %s; re-bootstrapping.", account
            )
            account.history_id = None
            if not dry_run:
                account.save(update_fields=["history_id"])
            return _sync_account(account, matters_by_name, dry_run=dry_run, full=True)
        if _is_rate_limit(e):
            # Bail on this account's tick; its cursor makes the next resume.
            logger.warning("Gmail rate limit hit for %s; deferring.", account)
            return stats
        raise

    logger.info("Gmail sync complete for %s: %s", account, stats)
    return stats


def sync(dry_run=False, full=False):
    """Run one sync tick across every connected mailbox.

    Returns an aggregate stats dict (plus per-account missing label names),
    or None when nothing is connected or no matter is label-linked. One
    account failing (expired token, API error) is logged and skipped so the
    other mailboxes still sync.
    """
    accounts = list(GmailAccount.objects.all())
    if not accounts:
        return None
    matters_by_name = _matters_by_label_name()
    if not matters_by_name:
        return None

    totals = _new_stats()
    missing = {}
    for account in accounts:
        try:
            stats = _sync_account(account, matters_by_name, dry_run=dry_run, full=full)
        except Exception:
            logger.exception("Gmail sync failed for %s", account)
            totals["failed"] += 1
            continue
        if stats is None:
            continue
        for key in _new_stats():
            totals[key] += stats.get(key, 0)
        if account.missing_labels:
            missing[account.address] = account.missing_labels
        if not dry_run:
            account.last_sync_at = timezone.now()
            account.save(update_fields=["last_sync_at"])

    return {**totals, "missing_labels": missing}


# --------------------------------------------------------------------------- #
# Per-matter resync (used by the Emails-tab "Link Gmail Label" UI)
# --------------------------------------------------------------------------- #
def resync_matter(matter):
    """Re-sync just one matter's emails across every connected mailbox.

    Used when a user links/changes/unlinks a matter's Gmail label: each
    account resolves the (possibly new) label name to its own label id,
    ingests what's under it, and reconciles its own rows. An account that
    can't resolve the name contributes nothing — and, because this is an
    explicit re-link, its rows from any previous label are removed. If the
    matter is unlinked, drops all its synced emails. No-op when nothing is
    connected. Returns a stats dict.
    """
    if not check_credentials():
        return None

    stats = _new_stats()

    if not matter.gmail_label_name:
        deleted, _ = Email.objects.filter(matter=matter).delete()
        stats["removed"] += deleted
        return stats

    for account in GmailAccount.objects.all():
        service = build_service(account)
        if not service:
            continue
        mapped, _missing = _resolve_labels(service, {matter.gmail_label_name: matter})
        seen = set()
        try:
            for label_id in mapped:
                for gmail_id in _list_label_message_ids(service, label_id):
                    seen.add(gmail_id)
                    _fetch_and_store(
                        service, account, matter, label_id, gmail_id, stats, False
                    )
        except HttpError as e:
            # Label vanished between resolve and list; keep this account's
            # rows and let the scheduled sync surface it via missing_labels.
            if e.resp.status in (400, 404):
                logger.warning(
                    "Gmail label %r for matter %s not listable in %s",
                    matter.gmail_label_name,
                    matter.pk,
                    account,
                )
                continue
            raise

        stale = (
            Email.objects.filter(matter=matter)
            .filter(_account_scope(account))
            .exclude(gmail_id__in=seen)
        )
        deleted, _ = stale.delete()
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
    accounts = list(GmailAccount.objects.select_related("user").order_by("id"))
    linked_matters = (
        Matter.objects.exclude(gmail_label_name__isnull=True)
        .exclude(gmail_label_name="")
        .count()
    )
    last_syncs = [a.last_sync_at for a in accounts if a.last_sync_at]
    return {
        "linked": bool(accounts),
        "accounts": accounts,
        # Distinct messages as the tab shows them (cross-mailbox duplicates
        # collapsed), not raw provenance rows.
        "synced_count": Email.objects.dedup().count(),
        "linked_matters": linked_matters,
        "missing_labels": {
            a.address: a.missing_labels for a in accounts if a.missing_labels
        },
        "last_sync_at": max(last_syncs) if last_syncs else None,
    }


def scheduled_sync():
    """django-q entry point (gmail-sync schedule)."""
    return sync()


def scheduled_sync_full():
    """django-q entry point (gmail-sync-weekly-full schedule)."""
    return sync(full=True)
