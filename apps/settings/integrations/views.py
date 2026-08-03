import json

import google_auth_oauthlib.flow
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from googleapiclient.discovery import build

import apps.drive.google as drive_google
import apps.mail.google as mail_google
from apps.mail.models import GmailAccount
from utils.prepare_path import prepare_path

CONTACTS_TOKEN_PATH = settings.GOOGLE_CONTACTS_TOKEN_PATH
CALENDAR_TOKEN_PATH = settings.GOOGLE_CALENDAR_TOKEN_PATH
DRIVE_TOKEN_PATH = settings.GOOGLE_DRIVE_TOKEN_PATH
EMAIL_TOKEN_PATH = settings.GOOGLE_EMAIL_TOKEN_PATH
GOOGLE_TOKEN_PATH = settings.GOOGLE_CLIENT_SECRET_PATH

# Map the <app> URL segment to its token file.
TOKEN_PATHS = {
    "contacts": CONTACTS_TOKEN_PATH,
    "calendar": CALENDAR_TOKEN_PATH,
    "drive": DRIVE_TOKEN_PATH,
    "email": EMAIL_TOKEN_PATH,
}


def _token_exists(file_path):
    prepare_path(file_path)

    try:
        with open(file_path, "r") as file:
            data = json.load(file)

        return "token" in data
    except (IOError, json.JSONDecodeError):
        return False


def _get_redirect_uri(request):
    return f"https://{request.get_host()}/settings/google/store"


def _create_flow(redirect_uri):
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        GOOGLE_TOKEN_PATH,
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/contacts",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/gmail.readonly",
            # Label create/rename only — message content stays read-only.
            # Lets the sync provision each mailbox's matter labels so users
            # only ever *apply* labels, never build the taxonomy.
            "https://www.googleapis.com/auth/gmail.labels",
        ],
    )

    flow.redirect_uri = redirect_uri
    return flow


def _get_auth_url(flow):
    return flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )


@login_required
def index(request):
    contacts_token = _token_exists(CONTACTS_TOKEN_PATH)
    calendar_token = _token_exists(CALENDAR_TOKEN_PATH)
    drive_token = _token_exists(DRIVE_TOKEN_PATH)
    # Email is per-user (GmailAccount rows), not a shared token file.
    email_token = mail_google.check_credentials()

    # Drive case-notes sync health (last sync, synced count, unmatched folders).
    drive_status = drive_google.get_sync_status() if drive_token else None
    # Gmail case-email sync health (per-account last sync, missing labels).
    gmail_status = mail_google.get_sync_status() if email_token else None

    context = {
        "app": "settings",
        "subapp": "integrations",
        "contacts_token": contacts_token,
        "calendar_token": calendar_token,
        "drive_token": drive_token,
        "drive_status": drive_status,
        "email_token": email_token,
        "gmail_status": gmail_status,
        "own_gmail_account": GmailAccount.objects.filter(user=request.user).first(),
        "label_root": settings.GMAIL_LABEL_ROOT,
    }

    return render(request, "settings/integrations/index.html", context)


def _forbidden_for(request, app):
    """Shared-token integrations (firm-wide files) are admin-only; email is
    per-user, so any signed-in user may connect their own mailbox."""
    return app != "email" and not request.user.is_admin


@login_required
def google_login(request, app):
    if _forbidden_for(request, app):
        return HttpResponseForbidden()
    redirect_uri = _get_redirect_uri(request)

    # Create OAuth2 flow instance
    flow = _create_flow(redirect_uri)

    authorization_url, state = _get_auth_url(flow)

    # Store the state to prevent CSRF attacks
    request.session["state"] = state
    request.session["app"] = app

    return redirect(authorization_url)


@login_required
def google_store(request):
    redirect_uri = _get_redirect_uri(request)

    # Create OAuth2 flow instance
    flow = _create_flow(redirect_uri)

    authorization_response = request.build_absolute_uri()
    flow.fetch_token(authorization_response=authorization_response)

    google_credentials = flow.credentials.to_json()

    app = request.session["app"]
    if _forbidden_for(request, app):
        return HttpResponseForbidden()

    if app == "email":
        # Per-user mailbox: the token lands on the requester's GmailAccount,
        # not the shared token file. The address comes from the mailbox
        # itself (getProfile), so sent mail can be recognized as "ours".
        service = build("gmail", "v1", credentials=flow.credentials)
        profile = service.users().getProfile(userId="me").execute()
        GmailAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "address": profile.get("emailAddress", ""),
                "token": google_credentials,
                # Fresh token, fresh mailbox view: force a bootstrap.
                "history_id": None,
            },
        )
        return redirect("/settings/integrations/")

    path = TOKEN_PATHS.get(app, CALENDAR_TOKEN_PATH)

    prepare_path(path)
    with open(path, "w") as file:
        file.write(google_credentials)

    # On (re)connecting the calendar, flush any local events that weren't synced
    # while disconnected — adopting existing Pending events on first connect and
    # clearing the backlog after a token outage.
    if app == "calendar":
        from apps.calendar import sync

        sync.reconcile()

    return redirect("/settings/integrations/")


@login_required
def google_logout(request, app):
    if _forbidden_for(request, app):
        return HttpResponseForbidden()
    if app == "email":
        # Disconnect the requester's own mailbox. Cascades that mailbox's
        # Email rows; messages a colleague's mailbox also holds stay visible
        # through their rows (promoted Documents are never touched).
        GmailAccount.objects.filter(user=request.user).delete()
        return redirect("/settings/integrations/")

    path = TOKEN_PATHS.get(app, CALENDAR_TOKEN_PATH)

    prepare_path(path)
    with open(path, "w") as file:
        file.write("")

    return redirect("/settings/integrations/")
