import json
from datetime import timedelta

import google.oauth2.credentials
from googleapiclient.discovery import build

CALENDAR_TOKEN_PATH = "google/calendar_tokens.json"


def check_credentials():
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

        calendar_id = "c_gu3p3ov90qi79he0i1p8k1qo0o@group.calendar.google.com"

        google_event = (
            service.events().insert(calendarId=calendar_id, body=new_event).execute()
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

    calendar_id = "c_gu3p3ov90qi79he0i1p8k1qo0o@group.calendar.google.com"

    if service:
        result = (
            service.events()
            .delete(
                calendarId=calendar_id,
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

        calendar_id = "c_gu3p3ov90qi79he0i1p8k1qo0o@group.calendar.google.com"

        result = (
            service.events()
            .update(
                calendarId=calendar_id,
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
