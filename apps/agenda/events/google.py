import json
import os
from datetime import timedelta

import google.oauth2.credentials

# noinspection PyPackageRequirements
from googleapiclient.discovery import build

from utils.prepare_path import prepare_path

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


def delete_event(event):
    service = build_service()

    if service:
        result = (
            service.events()
            .delete(
                calendarId=CALENDAR_ID,
                eventId=event.google_id,
            )
            .execute()
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
