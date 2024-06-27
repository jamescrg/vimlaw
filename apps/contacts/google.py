import json

import google.oauth2.credentials
from googleapiclient.discovery import build

CONTACTS_TOKEN_PATH = "google/contact_tokens.json"


def check_credentials():
    try:
        credential_file = open(CONTACTS_TOKEN_PATH, "r")
    except FileNotFoundError:
        return False
    credentials = credential_file.read()
    credential_file.close()
    if "token" in credentials:
        return True
    else:
        return False


def build_service():
    try:
        f = open(CONTACTS_TOKEN_PATH, "r")
        google_contacts_token = f.read()
        f.close()
    except FileNotFoundError:
        return False

    credentials = google_contacts_token

    if credentials:
        credentials = json.loads(credentials)
        credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
            credentials
        )
        service = build("people", "v1", credentials=credentials)
        return service

    else:
        return False


def add_contact(contact):
    service = build_service()

    if service:
        new_contact = {
            "names": [{"unstructuredName": contact.name}],
            "emailAddresses": [{"value": contact.email}],
            "phoneNumbers": [
                {
                    "value": contact.phone1,
                    "type": contact.phone1_label,
                },
                {
                    "value": contact.phone2,
                    "type": contact.phone2_label,
                },
                {
                    "value": contact.phone3,
                    "type": contact.phone3_label,
                },
            ],
        }

        result = service.people().createContact(body=new_contact).execute()

        if result:
            google_id = result["resourceName"]
            return google_id
        else:
            return None

    else:
        return None


def delete_contact(contact):
    service = build_service()

    if "people/" not in contact.google_id:
        contact.google_id = "people/" + contact.google_id

    if service:
        result = (
            service.people().deleteContact(resourceName=contact.google_id).execute()
        )

        if result:
            return True
        else:
            return False

    else:
        return False
