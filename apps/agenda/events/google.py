import json
import os
from datetime import timedelta
from logging import getLogger
from typing import Dict, List

import google.oauth2.credentials
from django.db.models import Max, Min
from google.api_core.exceptions import GoogleAPIError
from googleapiclient.discovery import build

from apps.agenda.events.models import Event
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
            "start": {
                "date": str(event.date),
                "timezone": "US/Eastern",
            },
            "end": {
                "date": str(event.date + timedelta(days=1)),
                "timezone": "US/Eastern",
            },
        }

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


def list_google_events(time_min: str, time_max: str) -> List[Dict]:
    """
    Fetch events from Google Calendar within the specified time range.

    Args:
        time_min: Start time in ISO format (YYYY-MM-DDTHH:MM:SSZ)
        time_max: End time in ISO format (YYYY-MM-DDTHH:MM:SSZ)

    Returns:
        List of event dictionaries from Google Calendar

    Raises:
        GoogleAPIError: If there's an error communicating with Google Calendar API
    """
    try:
        service = build_service()
        if not service:
            logger.error("Failed to build Google Calendar service")

            return []

        response = (
            service.events()
            .list(
                calendarId=CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        return response.get("items", [])

    except GoogleAPIError as e:
        logger.error(f"Google Calendar API error: {e}")

        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching events: {e}")

        return []


def remove_deleted_events() -> None:
    """
    Remove local events that no longer exist in Google Calendar.
    Fetches events from Google Calendar for the time period spanning all local events
    and deletes local events that don't have matching Google Calendar entries.
    """
    try:
        # Get all events with Google IDs
        app_events = Event.objects.filter(google_id__isnull=False)

        if not app_events.exists():
            logger.info("No events to synchronize")

            return

        # Calculate date range
        date_range = app_events.aggregate(min_date=Min("date"), max_date=Max("date"))

        first_date = date_range["min_date"] - timedelta(days=1)
        last_date = date_range["max_date"] + timedelta(days=1)

        # Convert to ISO format for Google Calendar API
        time_min = first_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = last_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Get Google Calendar events
        google_events = list_google_events(time_min, time_max)
        google_event_ids = {event["id"] for event in google_events}

        # Delete events that don't exist in Google Calendar anymore
        app_events.exclude(google_id__in=google_event_ids).delete()

    except Exception as e:
        logger.error(f"Error during event synchronization: {e}")


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
            pass

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
            "start": {
                "date": str(event.date),
            },
            "end": {
                "date": str(event.date + timedelta(days=1)),
            },
        }

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
