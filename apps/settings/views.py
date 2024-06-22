import json

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.shortcuts import render
from django.shortcuts import redirect
from django.shortcuts import get_object_or_404

import google.oauth2.credentials
import google_auth_oauthlib.flow
from apiclient.discovery import build

from accounts.models import CustomUser


@login_required
def index(request):
    f = open("/home/james/.google/cla_contacts_token.json", "r")
    google_contacts_token = f.read()
    f.close()
    if "token" in google_contacts_token:
        contacts_token = True
    else:
        contacts_token = False

    f = open("/home/james/.google/cla_calendar_token.json", "r")
    google_calendar_token = f.read()
    f.close()
    if "token" in google_calendar_token:
        calendar_token = True
    else:
        calendar_token = False

    context = {
        "page": "settings",
        "contacts_token": contacts_token,
        "calendar_token": calendar_token,
    }
    return render(request, "settings/content.html", context)


@login_required
def google_login(request, app):
    # direct the user to their login page to obtain an authorization code
    # based on sample code from https://developers.google.com/identity/protocols/oauth2/web-server

    # sets the url to return to when an authorization code has been obtained
    redirect_uri = "https://" + request.get_host() + "/settings/google/store"

    # builds the url to go to in order to obtain the authorization code
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "/home/james/.google/cla.json",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/contacts",
        ],
    )
    flow.redirect_uri = redirect_uri

    authorization_url, state = flow.authorization_url(
        # Enable offline access so that you can refresh an access token without
        # re-prompting the user for permission. Recommended for web server apps.
        access_type="offline",
        prompt="consent",
        # Enable incremental authorization. Recommended as a best practice.
        include_granted_scopes="true",
    )

    # this is to prevent cross site scripting attacks
    request.session["state"] = state

    # this allows the next request to determine where to store the credentials
    request.session["app"] = app

    return redirect(authorization_url)


@login_required
def google_store(request):
    redirect_uri = "https://" + request.get_host() + "/settings/google/store"

    state = request.session["state"]
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "/home/james/.google/cla.json",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/contacts",
        ],
        state=state,
    )
    flow.redirect_uri = redirect_uri

    authorization_response = request.build_absolute_uri()
    flow.fetch_token(authorization_response=authorization_response)

    # get the user credentials and package them as a json string
    credentials = flow.credentials
    google_credentials_json = credentials.to_json()

    # save the json credentials to the database
    user_id = request.user.id
    user = get_object_or_404(CustomUser, pk=user_id)
    app = request.session["app"]
    if app == "contacts":
        f = open("/home/james/.google/cla_contacts_token.json", "w")
        f.write(google_credentials_json)
        f.close()
    if app == "calendar":
        f = open("/home/james/.google/cla_calendar_token.json", "w")
        f.write(google_credentials_json)
        f.close()
    user.save()

    return redirect("/settings")


@login_required
def google_logout(request, app):
    if app == "contacts":
        f = open("/home/james/.google/cla_contacts_token.json", "w")
        f.write("")
        f.close()
    if app == "calendar":
        f = open("/home/james/.google/cla_calendar_token.json", "w")
        f.write("")
        f.close()

    return redirect("/settings")
