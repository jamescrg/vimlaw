import json

import google_auth_oauthlib.flow
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from utils.prepare_path import prepare_path

CONTACTS_TOKEN_PATH = "google/contact_tokens.json"
CALENDAR_TOKEN_PATH = "google/calendar_tokens.json"
GOOGLE_TOKEN_PATH = "google/google_tokens.json"


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

    context = {
        "page": "settings",
        "contacts_token": contacts_token,
        "calendar_token": calendar_token,
    }

    return render(request, "settings/content.html", context)


@login_required
def google_login(request, app):
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

    path = CONTACTS_TOKEN_PATH if app == "contacts" else CALENDAR_TOKEN_PATH

    prepare_path(path)
    with open(path, "w") as file:
        file.write(google_credentials)

    return redirect("/settings")


@login_required
def google_logout(request, app):
    path = CONTACTS_TOKEN_PATH if app == "contacts" else CALENDAR_TOKEN_PATH

    prepare_path(path)
    with open(path, "w") as file:
        file.write("")

    return redirect("/settings")
