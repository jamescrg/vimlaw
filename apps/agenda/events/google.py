import json
import os
from datetime import datetime, timedelta
from logging import getLogger

import google.oauth2.credentials
from dateutil import parser as date_parser
from googleapiclient.discovery import build

from utils.prepare_path import prepare_path

logger = getLogger(__name__)

CALENDAR_TOKEN_PATH = "google/calendar_tokens.json"
CALENDAR_ID = os.environ.get("CALENDAR_ID")


def check_credentials():
    prepare_path(CALENDAR_TOKEN_PATH)

    try:
        credential_file = open(CALENDAR_TOKEN_PATH, "r")
        credentials = credential_file.read()
        credential_file.close()
    except FileNotFoundError:
        return False

    if "token" in credentials:
        return True
    else:
        return False


def build_service():
    prepare_path(CALENDAR_TOKEN_PATH)

    f = open(CALENDAR_TOKEN_PATH, "r")
    google_calendar_token = f.read()
    f.close()

    credentials = google_calendar_token

    if credentials:
        credentials = json.loads(credentials)
        credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
            credentials
        )
        service = build("calendar", "v3", credentials=credentials)
        return service
    else:
        return False


def add_event(event):
    service = build_service()

    if service:
        new_event = {
            "summary": f"{event.matter} - {event.description}",
        }

        # Handle timed events vs all-day events
        if event.start_time and event.end_time:
            # Timed event - use dateTime format
            start_datetime = datetime.combine(event.date, event.start_time)
            end_datetime = datetime.combine(event.date, event.end_time)
            new_event["start"] = {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "US/Eastern",
            }
            new_event["end"] = {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "US/Eastern",
            }
        else:
            # All-day event - use date format
            new_event["start"] = {
                "date": str(event.date),
                "timeZone": "US/Eastern",
            }
            new_event["end"] = {
                "date": str(event.date + timedelta(days=1)),
                "timeZone": "US/Eastern",
            }

        # Add location if provided
        if event.location:
            new_event["location"] = event.location

        google_event = (
            service.events().insert(calendarId=CALENDAR_ID, body=new_event).execute()
        )

        if google_event:
            google_id = google_event.get("id")
            return google_id
        else:
            return None

    else:
        return None


def list_google_events(sync_token=None):
    """
    Fetch events from Google Calendar using incremental sync.

    Args:
        sync_token: Optional sync token for incremental sync. If None, performs full sync.

    Returns:
        Tuple of (events_list, next_sync_token)
        - events_list: List of event dictionaries (including cancelled events)
        - next_sync_token: Token to use for next incremental sync

    Raises:
        Exception: If sync token is invalid (410 error), caller should retry without token
    """
    try:
        service = build_service()
        if not service:
            logger.error("Failed to build Google Calendar service")
            return ([], None)

        all_events = []
        page_token = None

        while True:
            params = {
                "calendarId": CALENDAR_ID,
                "singleEvents": True,
                "showDeleted": True,  # Include cancelled events for sync
            }

            if sync_token:
                # Incremental sync - use sync token
                params["syncToken"] = sync_token
            else:
                # Full sync - cannot use orderBy with syncToken
                params["timeMin"] = datetime.now().isoformat() + "Z"
                params["maxResults"] = 2500

            if page_token:
                params["pageToken"] = page_token

            response = service.events().list(**params).execute()

            events = response.get("items", [])
            all_events.extend(events)

            page_token = response.get("nextPageToken")
            if not page_token:
                # No more pages
                next_sync_token = response.get("nextSyncToken")
                break

        logger.info(f"Fetched {len(all_events)} events from Google Calendar")
        return (all_events, next_sync_token)

    except Exception as e:
        # Check for expired sync token (HTTP 410)
        if hasattr(e, "resp") and e.resp.status == 410:
            logger.warning("Sync token expired, full sync required")
            raise  # Re-raise so caller can retry without token
        else:
            logger.error(f"Error fetching events from Google Calendar: {e}")
            return ([], None)


# def remove_deleted_events() -> None:
#     """
#     Remove local events that no longer exist in Google Calendar.
#     Fetches events from Google Calendar for the time period spanning all local events
#     and deletes local events that don't have matching Google Calendar entries.
#     """
#     try:
#         # Get all events with Google IDs
#         app_events = Event.objects.filter(google_id__isnull=False)
#
#         if not app_events.exists():
#             logger.info("No events to synchronize")
#
#             return
#
#         # Calculate date range
#         date_range = app_events.aggregate(min_date=Min("date"), max_date=Max("date"))
#
#         first_date = date_range["min_date"] - timedelta(days=1)
#         last_date = date_range["max_date"] + timedelta(days=1)
#
#         # Convert to ISO format for Google Calendar API
#         time_min = first_date.strftime("%Y-%m-%dT%H:%M:%SZ")
#         time_max = last_date.strftime("%Y-%m-%dT%H:%M:%SZ")
#
#         # Get Google Calendar events
#         google_events = list_google_events(time_min, time_max)
#         google_event_ids = {event["id"] for event in google_events}
#
#         # Delete events that don't exist in Google Calendar anymore
#         app_events.exclude(google_id__in=google_event_ids).delete()
#
#     except Exception as e:
#         logger.error(f"Error during event synchronization: {e}")


def delete_event(event):
    service = build_service()
    result = None

    if service:
        try:
            result = (
                service.events()
                .delete(
                    calendarId=CALENDAR_ID,
                    eventId=event.google_id,
                )
                .execute()
            )
        except Exception as err:
            # If the event is not found, it is already deleted, ignore the error
            print(
                f"The event was already deleted through the Google Calendar interface: {err}"
            )

        if result:
            return True
        else:
            return False

    else:
        return False


def edit_event(event):
    service = build_service()

    if service:
        revised_event = {
            "summary": f"{event.matter} - {event.description}",
        }

        # Handle timed events vs all-day events
        if event.start_time and event.end_time:
            # Timed event - use dateTime format
            start_datetime = datetime.combine(event.date, event.start_time)
            end_datetime = datetime.combine(event.date, event.end_time)
            revised_event["start"] = {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "US/Eastern",
            }
            revised_event["end"] = {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "US/Eastern",
            }
        else:
            # All-day event - use date format
            revised_event["start"] = {
                "date": str(event.date),
            }
            revised_event["end"] = {
                "date": str(event.date + timedelta(days=1)),
            }

        # Add location if provided
        if event.location:
            revised_event["location"] = event.location

        result = (
            service.events()
            .update(
                calendarId=CALENDAR_ID,
                eventId=event.google_id,
                body=revised_event,
            )
            .execute()
        )

        if result:
            return True
        else:
            return False

    else:
        return False


def sync_from_google():
    """
    Synchronize events from Google Calendar to local database.
    Uses incremental sync with sync tokens for efficiency.
    Conflict resolution: LawAdmin wins (local changes take precedence).
    """
    # Import here to avoid circular dependency
    from apps.agenda.events.models import CalendarSyncState

    if not check_credentials():
        logger.error("No Google Calendar credentials available")
        return

    if not CALENDAR_ID:
        logger.error("CALENDAR_ID environment variable not set")
        return

    logger.info(f"Starting Google Calendar sync for calendar: {CALENDAR_ID}")

    # Get or create sync state for this calendar
    sync_state, created = CalendarSyncState.objects.get_or_create(
        calendar_id=CALENDAR_ID
    )

    sync_token = sync_state.sync_token if not created else None

    try:
        # Fetch events from Google Calendar
        google_events, next_sync_token = list_google_events(sync_token)

        if google_events is None:
            logger.error("Failed to fetch events from Google Calendar")
            return

        logger.info(f"Processing {len(google_events)} events from Google Calendar")

        created_count = 0
        updated_count = 0
        deleted_count = 0
        skipped_count = 0

        for google_event in google_events:
            try:
                result = _process_google_event(google_event)
                if result == "created":
                    created_count += 1
                elif result == "updated":
                    updated_count += 1
                elif result == "deleted":
                    deleted_count += 1
                elif result == "skipped":
                    skipped_count += 1
            except Exception as e:
                logger.error(f"Error processing event {google_event.get('id')}: {e}")
                continue

        # Save new sync token
        if next_sync_token:
            sync_state.sync_token = next_sync_token
            sync_state.save()
            logger.info(f"Saved new sync token for {CALENDAR_ID}")

        logger.info(
            f"Sync completed: {created_count} created, {updated_count} updated, "
            f"{deleted_count} deleted, {skipped_count} skipped"
        )

    except Exception as e:
        # Handle expired sync token
        if "410" in str(e) or "Sync token" in str(e):
            logger.warning("Sync token expired, performing full sync")
            sync_state.sync_token = None
            sync_state.save()
            # Retry without token
            sync_from_google()
        else:
            logger.error(f"Error during Google Calendar sync: {e}")
            raise


def _process_google_event(google_event):
    """
    Process a single Google Calendar event.
    Returns: 'created', 'updated', 'deleted', or 'skipped'
    """
    from apps.agenda.events.models import Event

    google_id = google_event.get("id")
    status = google_event.get("status")

    # Handle deleted events
    if status == "cancelled":
        deleted = Event.objects.filter(google_id=google_id).delete()
        if deleted[0] > 0:
            logger.info(f"Deleted event {google_id}")
            return "deleted"
        return "skipped"

    # Parse Google event data
    try:
        event_data = _parse_google_event(google_event)
    except Exception as e:
        logger.error(f"Error parsing Google event {google_id}: {e}")
        return "skipped"

    # Check if event exists locally
    try:
        local_event = Event.objects.get(google_id=google_id)
        # Event exists - check if we should update it

        # Get Google's last updated timestamp
        google_updated = date_parser.parse(google_event.get("updated"))

        # LawAdmin wins: only update if Google is newer
        if local_event.updated_at and local_event.updated_at > google_updated:
            # Local is newer - push to Google instead
            logger.info(f"Local event {google_id} is newer, pushing to Google")
            edit_event(local_event)
            return "skipped"

        # Google is newer - update local
        for field, value in event_data.items():
            setattr(local_event, field, value)
        local_event.save()
        logger.info(f"Updated event {google_id}")
        return "updated"

    except Event.DoesNotExist:
        # Event doesn't exist locally - create it
        event_data["google_id"] = google_id
        Event.objects.create(**event_data)
        logger.info(f"Created event {google_id}")
        return "created"


def _parse_google_event(google_event):
    """
    Parse Google Calendar event into local Event model fields.
    Extracts: date, start_time, end_time, description, location
    Note: matter, party, status, user_id cannot be determined from Google data
    """
    from apps.matters.models import Matter

    event_data = {}

    # Parse summary (format: "Matter - Description")
    summary = google_event.get("summary", "")
    if " - " in summary:
        matter_name, description = summary.split(" - ", 1)
        # Try to find matter by name
        try:
            matter = Matter.objects.filter(name__icontains=matter_name).first()
            if matter:
                event_data["matter"] = matter
        except Exception:
            pass
        event_data["description"] = description
    else:
        event_data["description"] = summary

    # Parse date and times
    start = google_event.get("start", {})
    end = google_event.get("end", {})

    if "date" in start:
        # All-day event
        event_data["date"] = date_parser.parse(start["date"]).date()
        event_data["start_time"] = None
        event_data["end_time"] = None
    elif "dateTime" in start:
        # Timed event
        start_dt = date_parser.parse(start["dateTime"])
        end_dt = date_parser.parse(end["dateTime"])
        event_data["date"] = start_dt.date()
        event_data["start_time"] = start_dt.time()
        event_data["end_time"] = end_dt.time()

    # Parse location
    location = google_event.get("location", "")
    if location in ["Zoom", "Virtual", "Phone", "In-person"]:
        event_data["location"] = location

    return event_data
